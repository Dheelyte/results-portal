# School Results Portal — Architecture & Build Specification

**Client:** Self-Starters House Montessori School
**Built by:** HSD Technologies
**Audience:** the coding agent building this system
**Revision:** v2, 11 October 2026 — rewritten against photographs of the school's
physical report card. Supersedes v1, which described a simpler card that the
school does not use.

> **Before building anything, read `docs/CARD-FINDINGS.md`.** Eight questions in
> it are unanswered, and four of them change this schema. Sections below marked
> **⚠ UNCONFIRMED** are the author's reading of a photograph, not a decision the
> school has made. Build the confirmed parts; stop at the marked ones and ask.

---

## 0. Read this first

This is a **primary school results portal** for a Montessori school. Roughly
300–600 pupils, 20–40 staff, ~400 parent accounts. Peak concurrency is a few
hundred parents on the evening results are released, three times a year.

That scale drives every decision below. **Build a boring monolith.** No
microservices, no event bus, no Kubernetes, no CQRS, no GraphQL. A single
FastAPI application, a single Postgres database, a Next.js frontend, deployed as
containers on one host. If you find yourself reaching for infrastructure, you
have misread the problem.

The hard parts of this system are **not** scale. They are:

1. Correctness of computed scores (a wrong grade on a report card is a crisis).
2. Authorization (a teacher must never see another class; a parent must never
   see another family's child).
3. Workflow state (who can change what, at which stage).
4. Reproducing the school's existing report card faithfully — it is a dense,
   two-part document and the school will compare your output to it line by line.
5. The sheer volume of writing the card demands of teachers. See §8.2.

---

## 1. Domain

### 1.1 Academic structure

- A **school** runs **academic sessions** (e.g. 2026/2027).
- Each session has three **terms** (First, Second, Third).
- Each term has two **assessment periods**: First Half Term and Second Half Term.
  Each produces its own sheet with its own columns. This is the single most
  important structural fact about this system.
- Pupils are **enrolled** into a **class** for a session (e.g. "Primary 4").
- Each pupil belongs to a **house**.
- Each class **offers** a set of **subjects**, some of which are grouped under a
  parent heading (English contains five sub-subjects).
- Each class-subject is **assigned to a teacher** for that session.
- Each class has one **class teacher** per session.

### 1.2 The score sheet

Columns differ by half term. Both photographed sheets are headed **third term**.
**Assumption A1 (§14):** first and second term use these same two layouts with
the same columns. Not yet verified against a first-term sheet.

**First Half Term**

| Subject | CA Test 1 | CA Test 2 | CA Test 3 | CA Test 4 | CA Test 5 | CA Test Total | Mid Term Test | Mid Term Ave. | Grade |
|---|---|---|---|---|---|---|---|---|---|

**Second Half Term**

| Subject | CA Test 1 | CA Test 2 | CA Test 3 | CA Test 4 | CA Test 5 | CA Test Total | Exam | Total Weighted Average | 2nd Term Ave. | 1st Term Ave. | Annual Scores (Ave.) | Grade |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

Both sheets carry a **Marks Obtainable** row above the subjects, giving each
column's maximum, and a **Grand Total** row beneath them.

**⚠ UNCONFIRMED:** the actual maxima, the formula behind *Total Weighted
Average*, and how *1st/2nd Term Ave.* and *Annual Scores (Ave.)* are derived.
The requirements gathered in September said CA 40 / exam 60; the card's
structure neither confirms nor contradicts that. Do not hard-code any formula
until the school answers. Put all of them in `services/grading.py` behind named
functions so one edit changes the system.

### 1.3 Grading scale — as printed on the card

| Grade | Meaning | Range |
|---|---|---|
| A+ | Excellence | 90–100 |
| A | Very Good | 80–89 |
| B+ | Good | 70–79 |
| B | Fairly Good | 60–69 |
| C | Average | 50–59 |
| D | Below Average | 40–49 |
| E | Weak | 0–39 |

**⚠ UNCONFIRMED:** this contradicts the six-band scale (A 75+, no plus grades)
the school approved in September. Seed the card's scale, because it is what is
printed, and confirm before launch. The versioned design in §4.5 exists exactly
because this kind of disagreement happens.

### 1.4 Report card contents

**Header:** Date · Name of Pupil · Overall Percentage · Position (In grades) ·
Class · Year/Session · No. in Class · House

**1. Attendance Record:** Times School Opened · Times Present · Times Absent ·
Times Collected Late

**2. Health and Physical Growth:** Height beginning and end of term (m) ·
Weight beginning and end of term (kg)

**3. Cognitive Ability:** the score table of §1.2

**Assessment pages** — ten free-text narrative sections:

| Code | Section |
|---|---|
| A | Area of Curriculum: English Language Arts, Mathematics, Science, Social Studies, Computer Skills, Art & Music, Physical Education (seven sub-blocks) |
| B | Work/Study Habits |
| C | Attendance/Tardiness |
| D | Attitude |
| E | Classroom Behaviour |
| F | Outside Behaviour |
| G | Character Development |
| H | Peer Relations |
| I | Personal Development |
| J | Performance |

**Footer:** Class Teacher's Comment + signature · Head Teacher's Comment +
signature · Parent's Name + signature · "Please return this card to the School
on ______ when next term begins"

Note the narrative section A uses **seven coarse curriculum areas**, which are
not the same list as the eighteen scored subjects. Both lists must exist.

**Count: sixteen, not seventeen.** Seven curriculum areas under A, plus B
through J, is 7 + 9 = 16 written passages per pupil per term. Earlier revisions
of this document said seventeen throughout and sized the teacher workload at
510 passages for a class of 30; the correct figures are sixteen and 480. The
photographs are the authority here and they show sixteen. See
`docs/DECISIONS.md` D27.

**⚠ UNCONFIRMED:** whether *Position (In grades)* is filled in. The school said
they do not rank pupils; the card has the field. Until answered, store it as a
nullable free-text field that a head teacher may type into, and **never compute
a rank**.

### 1.5 Subjects

Scored subjects, in card order:

- **English** *(group heading, carries no scores of its own)*
  - Language Arts
  - Structure
  - Compr. & Poetry
  - Spelling & Reading
  - Creative Writing
- Mathematics
- Cultural Studies
- Geography
- History
- Science
- Social Studies
- Home Economics
- Computer
- Creative Art
- Penmanship
- Yoruba
- French
- Physical/Health Education

The card leaves blank rows for additions, so the list must be admin-editable and
the display order must be configurable.

### 1.6 Workflow

```
Admin sets up term and both assessment periods
      ↓
Teachers enter scores                        (per class-subject, per half term)
      ↓
Class teacher writes the ten narrative sections, attendance, growth
      ↓
Class teacher submits class                  (blocked until everything is complete)
      ↓
Head teacher reviews → approves, or returns with a note
      ↓
Admin publishes                              (whole class, or hold back individuals)
      ↓
Parents view / download PDF / acknowledge
```

After publication, **only the admin** may change a result, and every change
records actor, timestamp, before/after values, and a reason.

---

## 2. Technology stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.12, FastAPI | async throughout |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | typed `Mapped[]` style, no legacy Query API |
| Migrations | Alembic | every schema change ships as a migration |
| Validation | Pydantic v2 | separate `Create` / `Update` / `Read` schemas |
| Database | PostgreSQL 16 | single database, no sharding |
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind | server components by default |
| PDF | WeasyPrint + Jinja2 | HTML/CSS template → A4 PDF |
| Auth | Application-managed JWT, Argon2id hashing | see §5 |
| Object storage | S3-compatible (Cloudflare R2) | generated PDFs, pupil photos, school logo |
| Container | Docker + Docker Compose | api, web, postgres, caddy |
| Tests | pytest + pytest-asyncio, Playwright for E2E | real Postgres in tests, not SQLite |

### 2.1 Deliberate exclusions

Do not introduce these without being asked:

- **Keycloak.** HSD uses it elsewhere, but for ~450 accounts in one school it is
  operational overhead with no payoff. Application-managed auth is correct here.
- **Celery / Redis queue.** PDF generation for one pupil takes well under a
  second. Generate on demand, cache the artifact. If bulk generation for a whole
  class becomes slow, add `arq` then — not now.
- **AWS Lambda.** WeasyPrint has native binary dependencies and the workload is a
  stateful Postgres app. Containers on a single host are cheaper and simpler.
- **A rich text editor** for the narrative sections. Plain textarea with a
  character count. The PDF is plain text; a WYSIWYG would promise formatting the
  card cannot render.

### 2.2 Multi-tenancy

Carry a `school_id` column on every tenant-scoped table from the first migration,
and filter every query by it. Seed exactly one school.

Do **not** build tenant management UI, subdomain routing, or per-tenant config
screens. The column alone is cheap now and saves a painful migration if HSD
sells this to a second school. Everything beyond the column is speculative.

### 2.3 Configuration, not code

**Standing rule** (`docs/DECISIONS.md`, D14). Everything the school can change
is a row in the database, edited through the platform. Nothing in that set may
be a compiled-in constant that drives behaviour.

*Seeded* initial data is fine — the school should not meet a blank screen on day
one — but every seeded value must be editable afterwards. So §1.5's subject
list, §1.3's grade bands and §4.6's narrative sections all ship as seed rows.

None of these may exist anywhere in the codebase:

- a `CURRENT_TERM` constant — the active term is `terms.is_current`, set by an
  admin
- a hardcoded set of specialist subjects — a flag on the row, set by an admin
- an enum or literal list of subject names
- grade bands in Python — they are `grading_scales` and `grade_bands` rows
  (§4.5), versioned precisely so the school can change them

Seeding must be idempotent and must never re-assert a value the school has
since edited.

---

## 3. Repository layout

```
results-portal/
├── CLAUDE.md
├── docker-compose.yml
├── docker-compose.prod.yml
├── Caddyfile                    # dev reverse proxy
├── Caddyfile.prod               # prod reverse proxy, TLS
├── .env.example
├── .github/workflows/ci.yml     # lint, migrate, test on every push
├── docs/
│   ├── ARCHITECTURE.md          # this file
│   ├── CARD-FINDINGS.md         # open conflicts — read before building
│   ├── DECISIONS.md             # append an entry whenever you decide something
│   └── report-card/             # photographs of the physical card
│       ├── first-half-term.{jpg,HEIC}      # HEIC is the original
│       ├── second-half-term.{jpg,HEIC}
│       ├── narrative-page-1.{jpg,HEIC}
│       └── narrative-page-2.{jpg,HEIC}
├── api/
│   ├── pyproject.toml
│   ├── alembic/versions/
│   ├── src/app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── routers/
│   │   ├── services/
│   │   │   ├── academic.py      # sessions, terms, half terms, classes, houses
│   │   │   ├── subjects.py      # subject tree, offerings, teacher assignment
│   │   │   ├── marks.py         # the Marks Obtainable row
│   │   │   ├── pupils.py        # the roll and enrolment
│   │   │   ├── accounts.py      # accounts, resets, the guardian link
│   │   │   ├── grading.py       # every formula and the grade bands
│   │   │   ├── results.py       # entry, validation, class averages
│   │   │   ├── narrative.py     # sections, authorship, phrase bank
│   │   │   ├── setup.py         # the term readiness checklist
│   │   │   ├── workflow.py
│   │   │   ├── cumulative.py    # term and annual averages
│   │   │   ├── reportcard.py    # assembles the full card payload
│   │   │   ├── errors.py        # domain errors, mapped to status codes once
│   │   │   └── audit.py
│   │   ├── auth/
│   │   ├── authz/
│   │   ├── pdf/
│   │   │   ├── templates/
│   │   │   └── render.py
│   │   └── seed/
│   └── tests/
└── web/
    ├── app/
    │   ├── (auth)/
    │   │   ├── login/
    │   │   └── change-password/ # the must_change_password gate (§5.1)
    │   ├── (staff)/
    │   │   ├── admin/           # setup: checklist, calendar, classes,
    │   │   │                    #   subjects, pupils, accounts, assessment
    │   │   ├── entry/           # score entry grid
    │   │   ├── narrative/       # narrative writing screen
    │   │   ├── class/           # class teacher progress view
    │   │   └── review/          # head teacher review
    │   └── (parent)/children/
    ├── components/
    └── lib/
        ├── api/                 # generated from the OpenAPI schema
        ├── auth.tsx             # the signed-in user, token in memory only
        └── use-async.ts         # loading a resource, running an action
```

---

## 4. Data model

Primary keys are UUID v7. All timestamps are `timestamptz`, stored UTC, rendered
`Africa/Lagos`. All scores are `numeric(5,2)` — never `float`.

### 4.1 Identity and people

```sql
CREATE TABLE schools (
  id         uuid PRIMARY KEY,
  name       text NOT NULL,
  short_name text NOT NULL,
  address    text, phone text, email text, logo_url text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TYPE user_role AS ENUM ('admin','head_teacher','teacher','parent');

CREATE TABLE users (
  id                   uuid PRIMARY KEY,
  school_id            uuid NOT NULL REFERENCES schools(id),
  role                 user_role NOT NULL,
  email                citext,
  phone                text,
  password_hash        text NOT NULL,
  full_name            text NOT NULL,
  must_change_password boolean NOT NULL DEFAULT true,
  is_active            boolean NOT NULL DEFAULT true,
  last_login_at        timestamptz,
  failed_attempts      int NOT NULL DEFAULT 0,
  locked_until         timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT identifier_present CHECK (email IS NOT NULL OR phone IS NOT NULL)
);
CREATE UNIQUE INDEX ON users (school_id, email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX ON users (school_id, phone) WHERE phone IS NOT NULL;

CREATE TABLE houses (
  id        uuid PRIMARY KEY,
  school_id uuid NOT NULL REFERENCES schools(id),
  name      text NOT NULL,
  UNIQUE (school_id, name)
);

CREATE TABLE pupils (
  id               uuid PRIMARY KEY,
  school_id        uuid NOT NULL REFERENCES schools(id),
  admission_number text NOT NULL,
  first_name       text NOT NULL,
  middle_name      text,
  last_name        text NOT NULL,
  sex              text CHECK (sex IN ('M','F')),
  date_of_birth    date,
  house_id         uuid REFERENCES houses(id),
  photo_url        text,
  is_active        boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (school_id, admission_number)
);

CREATE TABLE guardian_pupils (
  guardian_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  pupil_id         uuid NOT NULL REFERENCES pupils(id) ON DELETE CASCADE,
  relationship     text,
  is_primary       boolean NOT NULL DEFAULT false,
  PRIMARY KEY (guardian_user_id, pupil_id)
);
```

### 4.2 Academic structure

```sql
CREATE TABLE academic_sessions (
  id         uuid PRIMARY KEY,
  school_id  uuid NOT NULL REFERENCES schools(id),
  name       text NOT NULL,              -- '2026/2027'
  starts_on  date NOT NULL,
  ends_on    date NOT NULL,
  is_current boolean NOT NULL DEFAULT false,
  UNIQUE (school_id, name)
);

CREATE TYPE term_number AS ENUM ('first','second','third');

CREATE TABLE terms (
  id                   uuid PRIMARY KEY,
  school_id            uuid NOT NULL REFERENCES schools(id),
  academic_session_id  uuid NOT NULL REFERENCES academic_sessions(id),
  number               term_number NOT NULL,
  starts_on            date NOT NULL,
  ends_on              date NOT NULL,
  times_school_opened  int CHECK (times_school_opened >= 0),
  next_resumption_on   date,
  card_return_on       date,             -- "return this card to the School on …"
  is_current           boolean NOT NULL DEFAULT false,
  UNIQUE (academic_session_id, number)
);

-- The structural key of this system: two sheets per term.
CREATE TYPE term_half AS ENUM ('first_half','second_half');

CREATE TABLE assessment_periods (
  id        uuid PRIMARY KEY,
  school_id uuid NOT NULL REFERENCES schools(id),
  term_id   uuid NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
  half      term_half NOT NULL,
  opens_on  date,
  closes_on date,
  UNIQUE (term_id, half)
);

CREATE TABLE classes (
  id          uuid PRIMARY KEY,
  school_id   uuid NOT NULL REFERENCES schools(id),
  name        text NOT NULL,
  level_order int  NOT NULL,
  is_active   boolean NOT NULL DEFAULT true,
  UNIQUE (school_id, name)
);

CREATE TABLE enrollments (
  id                  uuid PRIMARY KEY,
  school_id           uuid NOT NULL REFERENCES schools(id),
  pupil_id            uuid NOT NULL REFERENCES pupils(id),
  class_id            uuid NOT NULL REFERENCES classes(id),
  academic_session_id uuid NOT NULL REFERENCES academic_sessions(id),
  joined_on           date NOT NULL,
  left_on             date,
  status              text NOT NULL DEFAULT 'active',
  UNIQUE (pupil_id, academic_session_id)
);
```

### 4.3 Subjects, with grouping

English is a heading over five scored sub-subjects. A group row prints on the
card but holds no scores.

```sql
CREATE TABLE subjects (
  id                uuid PRIMARY KEY,
  school_id         uuid NOT NULL REFERENCES schools(id),
  name              text NOT NULL,
  parent_subject_id uuid REFERENCES subjects(id),
  is_group          boolean NOT NULL DEFAULT false,
  display_order     int NOT NULL DEFAULT 0,
  is_active         boolean NOT NULL DEFAULT true,
  UNIQUE (school_id, name),
  CONSTRAINT group_has_no_parent CHECK (NOT (is_group AND parent_subject_id IS NOT NULL))
);

CREATE TABLE class_subjects (
  id                  uuid PRIMARY KEY,
  school_id           uuid NOT NULL REFERENCES schools(id),
  class_id            uuid NOT NULL REFERENCES classes(id),
  subject_id          uuid NOT NULL REFERENCES subjects(id),
  academic_session_id uuid NOT NULL REFERENCES academic_sessions(id),
  display_order       int NOT NULL DEFAULT 0,
  UNIQUE (class_id, subject_id, academic_session_id)
);

CREATE TABLE teaching_assignments (
  id               uuid PRIMARY KEY,
  school_id        uuid NOT NULL REFERENCES schools(id),
  class_subject_id uuid NOT NULL REFERENCES class_subjects(id) ON DELETE CASCADE,
  teacher_user_id  uuid NOT NULL REFERENCES users(id),
  UNIQUE (class_subject_id)
);

CREATE TABLE class_teachers (
  id                  uuid PRIMARY KEY,
  school_id           uuid NOT NULL REFERENCES schools(id),
  class_id            uuid NOT NULL REFERENCES classes(id),
  academic_session_id uuid NOT NULL REFERENCES academic_sessions(id),
  teacher_user_id     uuid NOT NULL REFERENCES users(id),
  UNIQUE (class_id, academic_session_id)
);
```

A subject where `is_group = true` must never appear in `class_subjects` as a
scored row. Enforce in the service layer and test it.

### 4.4 Scores

```sql
-- The "Marks Obtainable" row. One row per sheet; per-class override optional.
CREATE TABLE marks_obtainable (
  id                   uuid PRIMARY KEY,
  school_id            uuid NOT NULL REFERENCES schools(id),
  assessment_period_id uuid NOT NULL REFERENCES assessment_periods(id) ON DELETE CASCADE,
  class_id             uuid REFERENCES classes(id),   -- NULL = all classes
  ca_test_1            numeric(5,2),
  ca_test_2            numeric(5,2),
  ca_test_3            numeric(5,2),
  ca_test_4            numeric(5,2),
  ca_test_5            numeric(5,2),
  mid_term_test        numeric(5,2),   -- first half only
  exam                 numeric(5,2),   -- second half only
  UNIQUE (assessment_period_id, class_id)
);

CREATE TABLE result_entries (
  id                   uuid PRIMARY KEY,
  school_id            uuid NOT NULL REFERENCES schools(id),
  assessment_period_id uuid NOT NULL REFERENCES assessment_periods(id),
  pupil_id             uuid NOT NULL REFERENCES pupils(id),
  class_subject_id     uuid NOT NULL REFERENCES class_subjects(id),
  ca_test_1            numeric(5,2) CHECK (ca_test_1 >= 0),
  ca_test_2            numeric(5,2) CHECK (ca_test_2 >= 0),
  ca_test_3            numeric(5,2) CHECK (ca_test_3 >= 0),
  ca_test_4            numeric(5,2) CHECK (ca_test_4 >= 0),
  ca_test_5            numeric(5,2) CHECK (ca_test_5 >= 0),
  ca_test_total        numeric(5,2) GENERATED ALWAYS AS (
                         CASE WHEN ca_test_1 IS NULL AND ca_test_2 IS NULL
                               AND ca_test_3 IS NULL AND ca_test_4 IS NULL
                               AND ca_test_5 IS NULL
                              THEN NULL
                              ELSE COALESCE(ca_test_1,0) + COALESCE(ca_test_2,0)
                                 + COALESCE(ca_test_3,0) + COALESCE(ca_test_4,0)
                                 + COALESCE(ca_test_5,0) END
                       ) STORED,
  mid_term_test        numeric(5,2) CHECK (mid_term_test >= 0),
  exam                 numeric(5,2) CHECK (exam >= 0),
  period_average       numeric(5,2),   -- Mid Term Ave. | Total Weighted Average
  grade_letter         text,           -- snapshot, written at approval
  grading_scale_id     uuid REFERENCES grading_scales(id),
  entered_by           uuid REFERENCES users(id),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assessment_period_id, pupil_id, class_subject_id)
);
CREATE INDEX ON result_entries (assessment_period_id, class_subject_id);
CREATE INDEX ON result_entries (assessment_period_id, pupil_id);
```

Upper bounds are **not** `CHECK` constraints, because each column's maximum
comes from `marks_obtainable` and the school can change it per sheet. Validate
against that row in `services/results.py`, and reject out-of-range scores at the
API boundary with the applicable maximum in the error message.

`period_average` is computed by `services/grading.py` and stored, because the
formula is **⚠ UNCONFIRMED**. Keeping it in one named function means one edit
when the school answers; a recompute command backfills existing rows.

### 4.5 Grading scale — versioned, and why

```sql
CREATE TABLE grading_scales (
  id             uuid PRIMARY KEY,
  school_id      uuid NOT NULL REFERENCES schools(id),
  name           text NOT NULL,
  effective_from date NOT NULL,
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE grade_bands (
  id        uuid PRIMARY KEY,
  scale_id  uuid NOT NULL REFERENCES grading_scales(id) ON DELETE CASCADE,
  min_score numeric(5,2) NOT NULL,
  max_score numeric(5,2) NOT NULL,
  letter    text NOT NULL,
  remark    text NOT NULL,
  sort_order int NOT NULL DEFAULT 0,
  CHECK (min_score <= max_score)
);
```

Seed the card's seven bands (§1.3). Grade letters are text, not an enum —
`A+` and `B+` exist, and the school may add more.

**The rule:** when a class is approved by the head teacher, write the resolved
`grade_letter` and `grading_scale_id` onto every result row.

If the school later changes a boundary, last term's printed cards must still say
what was printed. Recomputing would silently rewrite history, and a parent
holding a printed card would find it disagrees with the portal. Snapshot at
approval; never recompute a published grade. Before approval, compute on the fly
from the active scale.

### 4.6 Narrative assessment

```sql
CREATE TABLE narrative_sections (
  id            uuid PRIMARY KEY,
  school_id     uuid NOT NULL REFERENCES schools(id),
  code          text NOT NULL,     -- 'A.english_language_arts', 'B', 'C', …
  label         text NOT NULL,     -- 'English Language Arts', 'Work/Study Habits'
  group_label   text,              -- 'Area of Curriculum' for the A-block
  display_order int NOT NULL,
  is_active     boolean NOT NULL DEFAULT true,
  UNIQUE (school_id, code)
);

CREATE TABLE narrative_entries (
  id         uuid PRIMARY KEY,
  school_id  uuid NOT NULL REFERENCES schools(id),
  term_id    uuid NOT NULL REFERENCES terms(id),
  pupil_id   uuid NOT NULL REFERENCES pupils(id),
  section_id uuid NOT NULL REFERENCES narrative_sections(id),
  body       text,
  written_by uuid REFERENCES users(id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (term_id, pupil_id, section_id)
);
```

Narrative is **per term**, not per half term — the card carries one set of
written assessments for the whole term.

Seed the sixteen sections of §1.4 in card order: the seven curriculum areas
under group label "Area of Curriculum", then B through J.

**Who writes each section** (B1, answered; `docs/DECISIONS.md` D15). A
narrative section carries its own **per-class teacher assignment**, set by an
admin. Where no assignment exists, the class teacher writes it — which covers
the behavioural sections B through J and every non-specialist curriculum area.

The two lists of §1.4 are deliberately **not** linked. Mapping the seven
curriculum areas onto the eighteen scored subjects does not work cleanly:
"Computer Skills" → *Computer* and "Physical Education" →
*Physical/Health Education* are fine, but **"Art & Music" has no counterpart**
— the scored list has *Creative Art* and no music subject at all. An explicit
assignment sidesteps the problem and keeps authorship as data the school edits,
per §2.3.

This needs a table for the assignment — class, section, teacher — added in
milestone 3 alongside `narrative_sections`.

```sql
CREATE TABLE comment_bank (
  id         uuid PRIMARY KEY,
  school_id  uuid NOT NULL REFERENCES schools(id),
  scope      text NOT NULL,   -- a narrative_sections.code, or 'class_teacher' | 'head_teacher'
  text       text NOT NULL,
  is_active  boolean NOT NULL DEFAULT true
);
```

A class of 30 needs **480 written passages per term** (16 sections × 30 pupils)
from one class teacher. Without a strong phrase bank this feature will not be
used as intended. Treat the comment bank as core, not optional, and scope its
entries to each section so the suggestions are relevant.

### 4.7 Attendance and growth

```sql
CREATE TABLE attendance_records (
  id            uuid PRIMARY KEY,
  school_id     uuid NOT NULL REFERENCES schools(id),
  term_id       uuid NOT NULL REFERENCES terms(id),
  pupil_id      uuid NOT NULL REFERENCES pupils(id),
  times_present int NOT NULL CHECK (times_present >= 0),
  times_absent  int NOT NULL CHECK (times_absent  >= 0),
  times_late    int NOT NULL DEFAULT 0 CHECK (times_late >= 0),
  recorded_by   uuid REFERENCES users(id),
  UNIQUE (term_id, pupil_id)
);

CREATE TABLE growth_records (
  id              uuid PRIMARY KEY,
  school_id       uuid NOT NULL REFERENCES schools(id),
  term_id         uuid NOT NULL REFERENCES terms(id),
  pupil_id        uuid NOT NULL REFERENCES pupils(id),
  height_start_m  numeric(4,2) CHECK (height_start_m  > 0),
  height_end_m    numeric(4,2) CHECK (height_end_m    > 0),
  weight_start_kg numeric(5,2) CHECK (weight_start_kg > 0),
  weight_end_kg   numeric(5,2) CHECK (weight_end_kg   > 0),
  recorded_by     uuid REFERENCES users(id),
  UNIQUE (term_id, pupil_id)
);
```

`times_present + times_absent` must equal `terms.times_school_opened`, and
`times_present` must not exceed it. Postgres cannot express a cross-table CHECK
— enforce in `services/results.py` **and** with a trigger, so no path can write
a bad row. **⚠ UNCONFIRMED:** whether the school treats present + absent as
exactly equal to times opened, or allows a discrepancy.

### 4.8 Workflow state

Submission is per class; publication is per pupil.

```sql
CREATE TYPE class_term_state AS ENUM
  ('not_started','in_progress','submitted','returned','approved');

CREATE TABLE class_term_status (
  id           uuid PRIMARY KEY,
  school_id    uuid NOT NULL REFERENCES schools(id),
  class_id     uuid NOT NULL REFERENCES classes(id),
  term_id      uuid NOT NULL REFERENCES terms(id),
  state        class_term_state NOT NULL DEFAULT 'not_started',
  submitted_at timestamptz, submitted_by uuid REFERENCES users(id),
  reviewed_at  timestamptz, reviewed_by  uuid REFERENCES users(id),
  return_note  text,
  UNIQUE (class_id, term_id)
);

CREATE TYPE publication_state AS ENUM ('draft','published','withheld');

CREATE TABLE term_reports (
  id                    uuid PRIMARY KEY,
  school_id             uuid NOT NULL REFERENCES schools(id),
  term_id               uuid NOT NULL REFERENCES terms(id),
  pupil_id              uuid NOT NULL REFERENCES pupils(id),
  class_id              uuid NOT NULL REFERENCES classes(id),
  overall_percentage    numeric(5,2),
  position_text         text,          -- free text; never computed. See §1.4
  no_in_class           int,
  class_teacher_comment text,
  head_teacher_remark   text,
  promotion_decision    text,          -- third term only
  state                 publication_state NOT NULL DEFAULT 'draft',
  published_at          timestamptz, published_by uuid REFERENCES users(id),
  withheld_reason       text,
  parent_acknowledged_at timestamptz,  -- replaces the parent signature
  pdf_object_key        text,
  pdf_generated_at      timestamptz,
  UNIQUE (term_id, pupil_id)
);
```

### 4.9 Audit log

```sql
CREATE TABLE audit_log (
  id          uuid PRIMARY KEY,
  school_id   uuid NOT NULL REFERENCES schools(id),
  actor_id    uuid REFERENCES users(id),
  action      text NOT NULL,
  entity_type text NOT NULL,
  entity_id   uuid,
  before      jsonb,
  after       jsonb,
  reason      text,
  ip_address  inet,
  user_agent  text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_log (entity_type, entity_id, created_at DESC);
CREATE INDEX ON audit_log (school_id, created_at DESC);
```

Write a row for: every score or narrative change after approval, every publish,
withhold and release, every grading-scale or marks-obtainable change, every
account creation or password reset, and every failed login. A post-publication
edit **requires** a non-empty `reason`; reject the request without one.

---

## 5. Authentication and authorization

### 5.1 Authentication

- Argon2id password hashing (`argon2-cffi`).
- Access token: JWT, 30 minutes, held in memory on the client.
- Refresh token: opaque random string, hashed in the database, 30 days,
  `httpOnly` + `Secure` + `SameSite=Lax` cookie. Rotate on use; detect reuse.
- Accounts are **created by the admin**, never self-registered.
- New accounts get a generated temporary password and `must_change_password`.
- Lock for 15 minutes after 5 failed attempts; rate-limit login by IP too.

**Parent login identifier.** Accept **either email or phone** against the same
password. Many parents' email addresses are inactive, and an email-only reset
will strand them. Parent password reset is therefore **admin-initiated**: the
admin regenerates a temporary password and passes it on by SMS or WhatsApp.
Self-service email reset is for staff accounts only.

### 5.2 Authorization — enforce at the query layer

Route guards alone are not enough. A subject teacher hitting another class's
results must get a 404, and the filtering must happen where the data is fetched.

Implement `authz/scope.py` exposing one dependency per resource:

```python
async def scoped_class_subjects(user: CurrentUser, session: DbSession) -> Select:
    """Returns a SELECT already filtered to what this user may touch."""
```

Every router builds its query from a scope resolver. No router composes a raw
`select(Model)` against tenant data.

| Action | Admin | Head teacher | Class teacher | Subject teacher | Parent |
|---|---|---|---|---|---|
| Sessions, terms, assessment periods, classes, subjects | ✅ | — | — | — | — |
| Create users, assign teachers | ✅ | — | — | — | — |
| Grading scale, marks obtainable, narrative sections, comment bank | ✅ | — | — | — | — |
| Enter scores | — | — | own class-subjects | own class-subjects | — |
| Write narrative sections — behavioural (B–J) | — | — | own class | — | — |
| Write narrative sections — curriculum (A), non-specialist | — | — | own class | — | — |
| Write narrative sections — curriculum (A), specialist | — | — | — | own class-subjects | — |
| Attendance, growth records | — | — | own class | — | — |
| Submit class for review | — | — | own class | — | — |
| Approve / return class | — | ✅ all | — | — | — |
| Head teacher remark, promotion, position | — | ✅ all | — | — | — |
| Publish / withhold / release | ✅ | — | — | — | — |
| Edit after publication | ✅ (reason required) | — | — | — | — |
| View own children's published reports | — | — | — | — | ✅ |
| Acknowledge a report | — | — | — | — | ✅ |
| View audit log | ✅ | read-only | — | — | — |

Additional invariants:

- A teacher who is class teacher of 4A and subject teacher of French in 5B gets
  the union of both scopes — nothing wider.
- Parents see a `term_report` only when `state = 'published'`. A withheld or
  draft report returns the school-contact message, never a 403 that leaks the
  report's existence.
- Staff cannot read parent endpoints, and parents cannot read any staff endpoint.

---

## 6. Business rules

Every one of these lives in `services/`, never in a router or a component, and
ships with a unit test.

### R1 — Score validation
Each score is ≥ 0 and ≤ the matching column in `marks_obtainable` for that
assessment period (per-class row if present, otherwise the school-wide row).
The error names the applicable maximum. One decimal place.

### R2 — CA test total
Sum of the five CA test columns, null only when all five are null. Computed by
the database as a stored generated column, so no code path can disagree.

### R3 — Period average
First half: *Mid Term Ave.* Second half: *Total Weighted Average*.
**⚠ UNCONFIRMED formula.** Implement as two named functions in
`services/grading.py` with the current best guess clearly marked as a
placeholder, plus a `recompute-averages` management command. Do not scatter the
arithmetic.

### R4 — Grade
Resolved from the active scale before approval, from the snapshotted scale after
it (§4.5). Grade applies to the period average, not to a raw score.

### R5 — Term and annual averages
On the second-half sheet, *1st Term Ave.*, *2nd Term Ave.* and *Annual Scores
(Ave.)* are per subject, across the terms the pupil was present for. A pupil who
joined in second term averages over two terms, not three. Report the number of
terms counted alongside the figure so a parent can see why it differs.
**⚠ UNCONFIRMED:** whether a term's average is its second-half *Total Weighted
Average*, or a blend of both halves.

### R6 — Grand total and overall percentage
*Grand Total* is the column-wise sum down the subject rows, excluding group
headings. *Overall Percentage* is the pupil's aggregate as a percentage.
**⚠ UNCONFIRMED:** the exact definition of Overall Percentage.

### R7 — Group subjects carry no scores
A subject with `is_group = true` renders as a heading and has no result row.
Reject any attempt to write a score against one.

### R8 — Narrative completeness
A pupil's narrative is complete when every active section has a non-empty body.
Sixteen sections per pupil.

### R9 — Attendance bounds
`times_present + times_absent = terms.times_school_opened`, and
`times_present ≤ times_school_opened`. Service layer plus trigger.

### R10 — Class submission gate
A class teacher may submit only when all of these hold:
- every class-subject is complete for both assessment periods of the term
- every pupil's narrative is complete (R8)
- every pupil has a class teacher comment
- every pupil has an attendance record, and `times_school_opened` is set
- every pupil has a growth record

Return a structured list of what is missing, by subject, by pupil and by
section. "Cannot submit" with no explanation generates support calls every term.

### R11 — Position
Never computed. `position_text` is free text the head teacher may optionally
enter. There is no ranking query anywhere in this codebase.

### R12 — Publication
Publishing acts on a class, with an optional list of pupils to hold back.
Withheld pupils may be released individually later. A parent opening a
non-published report sees exactly:

> Result not yet available. Please contact the school.

### R13 — Post-publication edits
Admin only, reason required, audited. Regenerates the PDF under a new versioned
object key; the previously published PDF is retained, never overwritten.

### R14 — State transitions
Legal transitions only; anything else is 409.

```
not_started → in_progress → submitted → approved
                  ↑             ↓
                  └── returned ─┘
```
Scores and narrative become read-only for teachers on `submitted`. A `returned`
class reopens. After `approved`, only the admin may change anything.

---

## 7. API surface

REST, JSON, under `/api/v1`. FastAPI generates the OpenAPI schema; the frontend
client is generated from it, so never hand-write client types.

```
POST   /auth/login  /auth/refresh  /auth/logout  /auth/change-password

# Admin — setup
GET/POST   /sessions  /terms  /classes  /subjects  /houses
POST       /sessions/{id}/current                     # §2.3: set in the platform
PATCH      /terms/{id}                                # dates, times_school_opened
POST       /terms/{id}/current
GET/POST   /terms/{id}/assessment-periods             # POST upserts on `half`
GET/PUT    /assessment-periods/{id}/marks-obtainable
PATCH      /subjects/{id}                             # §1.5: editable, reorderable
GET/PUT    /classes/{id}/subjects
PUT        /class-subjects/{id}/teacher
PUT        /classes/{id}/class-teacher
GET/PUT    /classes/{id}/narrative-assignments        # B1 / D15
GET/POST   /pupils                                     # manual entry; see DECISIONS N8
PUT        /pupils/{id}/enrollment                    # place, or move class
GET/POST   /users           POST /users/{id}/reset-password
GET/POST   /guardians/{id}/children
GET/POST   /grading-scales  POST /grading-scales/{id}/activate
GET/PUT    /narrative-sections
GET/POST   /comment-bank
GET        /setup-checklist?term_id=

# Teachers — entry
GET    /my/assignments?term_id=
GET    /class-subjects/{id}/entries?assessment_period_id=
PUT    /class-subjects/{id}/entries                   # bulk upsert, main write path
GET    /classes/{id}/narrative?term_id=
PUT    /pupils/{id}/narrative?term_id=
PUT    /classes/{id}/attendance?term_id=
PUT    /classes/{id}/growth?term_id=
PUT    /classes/{id}/comments?term_id=
GET    /classes/{id}/progress?term_id=
POST   /classes/{id}/submit?term_id=                  # 422 + missing-items list

# Head teacher — review
GET    /review/queue?term_id=
GET    /classes/{id}/review?term_id=
PUT    /classes/{id}/remarks?term_id=
POST   /classes/{id}/approve?term_id=
POST   /classes/{id}/return?term_id=                  # { note }

# Admin — publication
POST   /classes/{id}/publish?term_id=                 # { withhold_pupil_ids, reason }
POST   /reports/{id}/release   /reports/{id}/withhold
PATCH  /entries/{id}                                  # { reason } required
GET    /audit?entity_type=&entity_id=

# Parent
GET    /my/children
GET    /my/children/{pupil_id}/reports
GET    /my/children/{pupil_id}/reports/{term_id}
GET    /my/children/{pupil_id}/reports/{term_id}/pdf  # 302 → signed URL, 5 min TTL
POST   /my/children/{pupil_id}/reports/{term_id}/acknowledge
```

`PUT /class-subjects/{id}/entries` is the most-used write in the system. It takes
an array of `{ pupil_id, ca_test_1..5, mid_term_test | exam }`, validates every
row against `marks_obtainable`, and applies all or none. Return per-row errors
keyed by `pupil_id` so the grid can highlight the offending cells.

`POST /terms` creates the term **and both of its assessment periods**, because
§1.1 states the two halves as a fact about the domain rather than an option
(`docs/DECISIONS.md` D36). The seven verbs marked above that this section
originally omitted are each justified in D37; none of them is new
functionality, they are the missing halves of requirements stated elsewhere in
this document.

Every endpoint in the admin block is admin-only, declared in the route
signature through `authz/dependencies.py` and asserted cell by cell against
§5.2 in `tests/integration/test_setup_authz.py`. A structural test there fails
if any `/api/v1` route outside `/auth` is ever mounted without a capability
gate.

---

## 8. Frontend

Next.js App Router. Server components by default; client components only where
there is real interactivity.

### 8.1 Score entry grid

Teachers will use this on an Android phone, on patchy data, for 30 pupils across
up to eight numeric columns. If it is slower than their current paper sheet they
will not use the portal.

- Columns follow the active assessment period: five CA tests plus Mid Term Test,
  or five CA tests plus Exam. CA Test Total, period average and grade are
  read-only and update live.
- The **Marks Obtainable** row pins to the top of the grid so the teacher can
  always see each column's maximum.
- Keyboard: `Enter` and `↓` move down the same column, `Tab` moves across.
- Validation inline and immediate — a red cell naming the maximum, not a modal.
- **Autosave** the dirty set every 20 seconds and on blur, with a visible
  "Saved 14:32" / "Saving…" / "Not saved — retrying" indicator.
- **Draft persistence to `localStorage`**, keyed by class-subject and period, so
  a dropped connection loses nothing. Reconcile on reload and say what was
  recovered.
- Below 640px, switch from a table to one card per pupil. Never ship a
  horizontally scrolling eight-column table on a phone.

### 8.2 Narrative writing screen

This is the heaviest task in the system — sixteen passages per pupil, 480 for
a class of 30 — and it belongs to one person, the class teacher.

- Work **pupil by pupil**, not section by section: one pupil, all sixteen
  sections on a page, with previous/next pupil navigation.
- Each section is a plain textarea with a character count and a **phrase bank**
  button scoped to that section.
- Autosave and localStorage drafts, exactly as the grid.
- A progress indicator across the class: "12 of 30 pupils complete".
- Let the teacher copy a section's text from the previous pupil as a starting
  point. They will otherwise do it through the clipboard anyway, and an explicit
  control is honest about it.

If the school confirms all sixteen sections, raise the workload with them
before launch. A reduced set is a product decision, not a technical one.

### 8.3 Class teacher progress view

One page per class: every subject with its state and owner, for both assessment
periods; then the class teacher's own tasks — narrative, attendance, growth,
comments. **Send to head teacher** is disabled until R10 passes, with the
outstanding items listed beneath it.

### 8.4 Head teacher review

Queue of submitted classes. Opening one shows each pupil's card as the parent
will see it, with fields for the remark, the optional position text, and, in
third term, the promotion decision. Approve, or return with a note.

### 8.5 Parent view

The lightest page in the system. Server-rendered, **target under 150 KB** first
load, no client-side fetching for the report itself.

- Login → children as cards → published terms → the report card.
- A prominent **Download PDF** button and an **Acknowledge** action, which
  replaces the parent signature and the physical return of the card.
- Withheld or unpublished: the R12 message, nothing else.

Assume a 3G connection on a low-end Android device, and test against that.

---

## 9. Report card PDF

Jinja2 → WeasyPrint → A4 portrait. The photographs in `docs/report-card/` are
the specification; match them before improving anything.

Structure, in order:

1. **Header** — school name, logo, term and half-term title
2. Date · Name of Pupil · Overall Percentage · Position · Class · Year/Session ·
   No. in Class · House
3. **1. Attendance Record** — opened, present, absent, collected late
4. **2. Health and Physical Growth** — height and weight, start and end of term
5. **3. Cognitive Ability** — the score table, Marks Obtainable row at the top,
   English as a spanning group heading over its five sub-rows, Grand Total at
   the foot
6. **Key** — the grade bands in force for that report, printed from the
   snapshotted scale, not the current one
7. **Assessment pages** — the sixteen narrative sections, A through J, with
   "Area of Curriculum" grouping its seven
8. **Footer** — class teacher comment, head teacher comment, parent
   acknowledgement, and the card return date

Requirements:

- **Cumulative columns render conditionally.** Under A1 the second-half sheet
  always carries *2nd Term Ave.*, *1st Term Ave.* and *Annual Scores (Ave.)*,
  but they are only meaningful once those terms exist. Render a column only when
  the pupil has results for that term: none in first term, one in second, both
  plus the annual average in third. Never print an empty or zero-filled column.
  This is also what makes A1 cheap to reverse — if the earlier terms turn out to
  print fewer columns, the template already omits them.
- Deterministic output: same data renders byte-identically, so regeneration is
  verifiable.
- Under 300 KB per file.
- Stored at `reports/{session}/{term}/{admission_number}-{version}.pdf`, served
  only through short-lived signed URLs. A guessable public URL would let anyone
  enumerate the school's results.
- Golden-file test: a fixed fixture pupil renders to a PDF whose extracted text
  matches a committed expected output, for both the first-half and second-half
  layouts.

---

## 10. Testing

| Layer | Tool | Coverage |
|---|---|---|
| Unit | pytest | Every rule in §6. Grade boundaries at 39/40/49/50/59/60/69/70/79/80/89/90. CA totals with missing tests. Averages with 1, 2 and 3 terms present. Attendance bounds. |
| Integration | pytest + real Postgres | Every endpoint, every role, including denied cases. |
| Authorization | pytest | Each endpoint × each role, asserting allow or 403/404. The most valuable suite in the project — write it early. |
| Workflow | pytest | Every legal transition, a rejection for each illegal one. |
| PDF | pytest | Golden files for both half-term layouts. |
| E2E | Playwright | Full term: set up → enter both periods → narrative → submit → approve → publish → parent downloads and acknowledges. |

Do not use SQLite. Generated columns, enums, `citext` and triggers behave
differently; tests would pass against a database you do not run.

Seed data: one school, two classes, 10 pupils each, the full subject tree with
English grouped, 3 teachers, 1 head teacher, 1 admin, 8 parents — one of whom
has two children in different classes, and one pupil who joined in second term.
Those last two fixtures catch most multi-child and cumulative-average bugs.

---

## 11. Deployment and operations

Single host, Docker Compose, Caddy terminating TLS.

Two hostnames under one registrable domain (`docs/DECISIONS.md`, D13):

```
<domain>      → caddy → web (Next.js :3000)
api.<domain>  → caddy → api (FastAPI/uvicorn :8000)
                api   → postgres :5432
                      → R2 (object storage)
```

Both must share a registrable domain, so browser requests from the web app to
the API are cross-origin but still **same-site** — which is what lets the
refresh-token cookie of §5.1 keep `SameSite=Lax`.

- All configuration from environment variables; `.env.example` lists every key.
  No secrets in the repository.
- `/healthz` (liveness) and `/readyz` (database reachable), on the **API host
  only**.
- Structured JSON logs to stdout. Never log scores, narrative text or tokens.
- Sentry with PII scrubbing on.
- **Backups:** nightly `pg_dump` to R2, 30 days retained, plus a dump taken
  immediately before every publish. Results data is irreplaceable — no teacher
  will rewrite 480 passages. Document and test the restore procedure; an
  untested backup is not a backup.
- Migrations run as an explicit deploy step, never automatically at startup.

---

## 12. Build order

Each milestone ends green — tests passing, migrations applied — before the next
begins. Do not start a milestone's frontend until its API is tested.

| # | Milestone | Done when |
|---|---|---|
| 0 | Settle the **blocking** items in §13 | Recorded in `docs/DECISIONS.md` |
| 1 | Skeleton: Compose, FastAPI, Postgres, Alembic, CI, health checks | `docker compose up` serves `/healthz` |
| 2 | Auth: users, login, refresh, password change, lockout | Auth tests pass for all four roles |
| 3 | Schema: every table in §4, seed data, subject tree | `alembic upgrade head` from empty; constraints proven by tests |
| 4 | Authorization scopes + the §5.2 matrix as tests | Every cell has a passing allow or deny test |
| 5 | Admin setup API + screens, assessment periods, marks obtainable | An admin configures a full term from an empty database |
| 6 | Score entry API + grid (§8.1), both period layouts | A teacher enters a full class on a phone viewport; autosave and recovery verified |
| 7 | Narrative screen (§8.2), attendance, growth, phrase bank | A class teacher completes one pupil's sixteen sections and moves to the next |
| 8 | Submission gate (R10) | Submission blocked with an accurate missing-items list, allowed when complete |
| 9 | Head teacher review, approve, return, grade snapshot | Approval writes `grade_letter` and `grading_scale_id` on every row |
| 10 | Publication, withhold, release, audit log | Withheld pupil's parent sees the R12 message; every action audited |
| 11 | PDF, both layouts, signed URLs | Golden-file tests pass; a guessed key 403s |
| 12 | Parent portal and acknowledgement | Under 150 KB first load; multi-child parent sees both children |
| 13 | Hardening: rate limits, backups, restore drill, E2E | Full-term E2E passes; a restore is performed and documented |

Milestone 0 is short. The four conflicts that genuinely changed the schema were
resolved when this spec was rewritten against the card, and the design absorbs
most of what is still open: the grading scale is versioned data, the column
maxima are configuration, and every formula sits behind a named function. Only
the three items marked **blocking** in §13 must be answered before code. The
rest are needed by the milestone named beside them.

Milestone 4 before 5 is deliberate — retrofitting authorization onto built
endpoints is how school portals leak results.

---

## 13. Open items

Record every answer in `docs/DECISIONS.md` with the date and who decided. Do not
guess and build.

### Blocking — answered 2026-10-20

All three were settled by the client on 2026-10-20. Full wording and
consequences in `docs/DECISIONS.md` (B1–B3). Summary:

| # | Question | Answer |
|---|---|---|
| B1 | Who writes the narrative for specialist subjects? | **Split.** The specialist teacher writes the curriculum-area section for their own subject; the class teacher writes the remaining curriculum areas and all of B–J. §5.2 updated. **Still open:** which of the seven curriculum areas count as specialist, and how "Art & Music" maps to the scored subjects — needed by milestone 3. |
| B2 | Is the head teacher also the admin? | **No — two distinct roles.** The head teacher approves results; a separate admin sees a portal-wide overview. §1.6's approve-then-publish workflow stands unchanged, and `users.role` remains the single-value enum of §4.1. |
| B3 | Which term is go-live, must earlier terms be imported? | **No import of earlier terms.** No historical-import milestone, no CSV format. The cumulative columns of §9 therefore render empty in the first year and are omitted rather than zero-filled, exactly as §9 already requires. **Still open, now low-stakes:** which term is go-live. |

### Needed before the milestone shown

| # | Question | Needed by |
|---|---|---|
| N1 | Which grading scale is current — the card's seven bands, or the six-band scale approved in September? | 9 (grade snapshot) |
| N2 | Marks obtainable for CA Test 1–5, Mid Term Test and Exam. Does 40/60 survive as CA Total vs Exam? | 5 (setup) — **reached, not blocking.** The screen and the table are built and nothing defaults; the school's own numbers are simply not in yet, so R1's validation has nothing real to check against. A photograph of a **filled-in** card would settle this, and probably N1 and N3 with it. |
| N3 | The *Total Weighted Average* formula, how 1st/2nd Term Ave. and Annual Scores (Ave.) are derived, **and whether a period average is rounded before a grade band is read from it** — the card's own bands leave 39.5 in no band (`docs/DECISIONS.md` D43). | 6 |
| N4 | Is *Position (In grades)* filled in, and in what form? | 9 |
| N5 | Do parents receive the first-half sheet at mid term, or only the full card at term end? | 10 (publication) |
| N6 | Do health and growth, house, times collected late, and the parent signature carry over to the digital card? | 11 (PDF) |
| N7 | All sixteen narrative sections, or a reduced set? | 7 |
| N9 | Teacher devices and connectivity — school Wi-Fi, or personal phones on mobile data at home? | 6 (offline behaviour) |

`docs/CARD-FINDINGS.md` holds the photographic evidence behind N1–N7.

### Project-level — not code, but they decide whether this lands

- **Hosting account, domain and who pays.** Deployed into HSD's account as a
  service, or the school's own? This decides who holds the backups and what
  happens to the data if the relationship ends.
- **Pilot scope.** Which classes, which term, and whether the school runs paper
  and portal in parallel for one term. Most schools need the parallel run to
  trust the output.
- **Support after handover.** Who a teacher calls at 9pm the night before
  results are released, and who holds the admin account day to day.
- **Data protection.** This system holds minors' records. Nigeria's Data
  Protection Act applies; the school will need a privacy notice and HSD a
  processing agreement with them. Get this checked by someone qualified — it is
  not covered by anything in this document.

---

## 14. Working assumptions

Each of these is a decision taken to keep building, not a fact the school has
confirmed. They are written here so they can be found and reversed. When one is
confirmed or overturned, move it to `docs/DECISIONS.md` with the date.

| # | Assumption | Cost to reverse |
|---|---|---|
| A1 | First and second term use the same two sheet layouts, with the same columns, as the photographed third-term sheets. | **Low.** The PDF already omits cumulative columns with no data (§9). A narrower earlier-term layout needs only a template variant. |
| A2 | The current grading scale is the card's seven bands (A+ 90–100 … E 0–39), not the six-band scale approved in September. | **Low.** Scales are versioned rows (§4.5). Seed a new scale; published grades are snapshotted and stay correct. |
| A3 | *Total Weighted Average* = CA Test Total + Exam. **Placeholder.** | **Low before launch, high after.** One function in `services/grading.py` plus a `recompute-averages` command. Once a term is published, recomputing rewrites parents' figures. |
| A4 | A term's contribution to the annual average is that term's second-half *Total Weighted Average*, not a blend of both halves. | **Low.** One function in `services/cumulative.py`. |
| A5 | `times_present + times_absent` equals `times_school_opened` exactly. | **Low.** Relax the trigger and the service check. |
| A6 | The narrative is written once per term, not per half term. | **Medium.** `narrative_entries` is keyed on `term_id`; moving to half term is a migration plus a rework of §8.2. |
| A7 | Parents log in with email **or** phone, and parent password resets are admin-initiated rather than by email. | **Low.** Both paths exist in the schema. |
| A8 | A digital acknowledgement by the parent replaces the physical signature and the returned card. | **Low** technically. The school may still want paper; that is their call, not a code change. |
| A10 | Deployment is a single host running Docker Compose, with Caddy terminating TLS for one domain. No staging environment is modelled in the repository. | **Low.** A third compose overlay and a second Caddy site block. Taken in milestone 1; see `docs/DECISIONS.md` D8. |
| A12 | A term's dates fall inside its session's, and each half term's window inside its term's. Enforced; see `docs/DECISIONS.md` D39. | **Low.** One guard each in `services/academic.py`. |
| A13 | A sheet's Marks Obtainable row counts as configured once its terminal column (Mid Term Test or Exam) and at least one CA test have a maximum — not all five. | **Low.** One predicate in `services/marks.py`. Tied to N2: a definite answer replaces the judgement. |
| A14 | A column maximum may not be lowered below a score already entered against it; the admin raises it or corrects the entries. | **Low.** One check in `services/marks.py`, and §4.4 still permits the change itself. |
| A15 | Grade bands must cover every **whole** mark from 0 to 100 without overlapping. Fractional coverage is deliberately not claimed, pending N3. | **Low.** One function in `services/grading.py`, with a test that fails on purpose when N3 lands. |
| A16 | The staff screens are client-rendered, because the session cookie is scoped to `api.<domain>` and the web server cannot read it. | **Low** for the setup screens. **Open** for §8.5's parent view, whose 150 KB server-rendered target this does not reach — three routes out, none foreclosed, in `docs/DECISIONS.md` D41. |
| A11 | The web app and the API stay under **one registrable domain** (`<domain>` and `api.<domain>`), so browser requests between them are cross-origin but same-site. | **Low** while it holds — CORS origin and cookie attributes are configuration. **Medium** if they ever land on unrelated domains: that forces `SameSite=None; Secure`, removes SameSite's CSRF defence so explicit CSRF tokens are needed, and runs into Safari's ITP. See `docs/DECISIONS.md` D13. |
