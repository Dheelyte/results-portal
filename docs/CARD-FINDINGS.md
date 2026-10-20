# Report card review — conflicts with the approved requirements

Source: four photographs of the school's physical card, third term, both half-term
sheets plus the narrative pages. Reviewed 11 October 2026.

**The approved requirements document describes a different, simpler report card
than the one the school actually uses.** Seven conflicts, four of which change
the data model. Do not start building until these are settled.

Both photographed sheets are headed **third term** — one First Half Term, one
Second Half Term. The spec assumes the earlier terms use the same two layouts
(assumption A1 in `ARCHITECTURE.md` §14); a first-term sheet would confirm it.

---

## 1. The grading scale is wrong

| Approved requirements | Printed on the card |
|---|---|
| A 75–100 | **A+ Excellence 90–100** |
| B 65–74 | **A Very Good 80–89** |
| C 55–64 | **B+ Good 70–79** |
| D 45–54 | **B Fairly Good 60–69** |
| E 40–44 | **C Average 50–59** |
| F 0–39 | **D Below Average 40–49** |
| — | **E Weak 0–39** |

Seven bands with plus-grades, not six. Every boundary differs. The "A is 75"
answer confirmed in September does not match the card in use.

## 2. Scoring is five CA tests plus an exam, not one CA score

The card's cognitive-ability table runs:

**First half term:** CA Test 1 · 2 · 3 · 4 · 5 · CA Test Total · Mid Term Test ·
Mid Term Ave. · Grades

**Second half term:** CA Test 1 · 2 · 3 · 4 · 5 · CA Test Total · Exam ·
Total Weighted Average · 2nd Term Ave. · 1st Term Ave. · Annual Scores (Ave.) ·
Grades

The approved spec has a single CA score out of 40 plus an exam out of 60. The
real card has five separate CA test columns, and a **Marks Obtainable** row
meaning each column's maximum is set by the school per sheet, not fixed at 40/60.

## 3. There are two assessment sheets per term, not one

"First Half Term" and "Second Half Term" are separate sheets with different
columns. The spec assumes one set of scores per term. This roughly doubles the
score entry work and changes the primary key of the results table.

## 4. Behaviour is written narrative, not 1–5 ratings

The spec has configurable traits rated 1 to 5. The card has ten free-text
sections, each about three ruled lines:

- **A) Area of Curriculum** — English Language Arts, Mathematics, Science,
  Social Studies, Computer Skills, Art & Music, Physical Education
- **B.** Work/Study Habits
- **C.** Attendance/Tardiness
- **D.** Attitude
- **E.** Classroom Behaviour
- **F.** Outside Behaviour
- **G.** Character Development
- **H.** Peer Relations
- **I.** Personal Development
- **J.** Performance

This is a Montessori narrative report. It is a different screen, a different
table, and a much heavier writing load for teachers — seventeen paragraphs per
pupil per term, on top of the scores.

## 5. The card has a Position field

The card prints **Position (In grades)** and **No. in Class** in its header. The
school said in September that they do not rank pupils, and the spec forbids
computing position anywhere. One of the two is out of date.

## 6. Attendance has four fields, not two

Times School Opened · Times Present · **Times Absent** · **Times Collected Late**.
The spec models only the first two.

## 7. Sections absent from the spec entirely

- **Health and Physical Growth** — height and weight, beginning and end of term
- **House** — the school runs a house system
- **Overall Percentage** and **Grand Total**
- **Subject grouping** — English is a parent heading over five sub-subjects
  (Language Arts, Structure, Compr. & Poetry, Spelling & Reading, Creative
  Writing); the spec treats all subjects as a flat list
- **Signatures** — class teacher, head teacher, and **parent**, with
  "Please return this card to the School when next term begins"

### Full subject list from the card

English (Language Arts, Structure, Compr. & Poetry, Spelling & Reading, Creative
Writing) · Mathematics · Cultural Studies · Geography · History · Science ·
Social Studies · Home Economics · Computer · Creative Art · Penmanship · Yoruba ·
French · Physical/Health Education, plus blank rows for additions.

Note this is a different and finer list than the seven curriculum areas used for
the narrative comments.

---

## What the school must confirm

1. **Which grading scale is current** — the card's seven bands, or the six-band
   scale approved in September?
2. **Marks obtainable** for each column: CA Test 1–5, Mid Term Test, Exam. Does
   the 40/60 split survive as CA Total vs Exam?
3. **Total Weighted Average** — the exact formula, and how 1st/2nd Term Ave. and
   Annual Scores (Ave.) are derived.
4. **Position** — is it filled in? If so, in what form ("In grades" suggests a
   band, not a rank)?
5. **Half-term publication** — do parents receive the first-half-term sheet on
   its own at mid term, or only the full card at the end of term? Both sheets
   are built either way; this decides whether publication runs twice a term.
6. **Keep in the digital version?** Health and physical growth, house, times
   collected late, parent signature and card return.
7. **Narrative load** — seventeen written sections per pupil per term is heavy.
   Does the school want all of them digitised, or a reduced set?

Record the answers in `docs/DECISIONS.md` and update `docs/ARCHITECTURE.md`
before any schema work begins.
