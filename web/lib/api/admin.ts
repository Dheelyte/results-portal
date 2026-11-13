/**
 * The admin setup surface of ARCHITECTURE.md §7, as typed functions.
 *
 * One function per endpoint, named after what the admin is doing rather than
 * after the HTTP verb. Types are the generated ones throughout; this file
 * adds no shapes of its own.
 */

import { request, requestBlob, type Schemas } from "./client";

export type AcademicSession = Schemas["AcademicSessionRead"];
export type Term = Schemas["TermRead"];
export type AssessmentPeriod = Schemas["AssessmentPeriodRead"];
export type SchoolClass = Schemas["ClassRead"];
export type House = Schemas["HouseRead"];
export type Subject = Schemas["SubjectRead"];
export type ClassSubject = Schemas["ClassSubjectRead"];
export type MarksObtainable = Schemas["MarksObtainableRead"];
export type Pupil = Schemas["PupilRead"];
export type PupilPage = Schemas["PupilPageRead"];
export type Account = Schemas["AccountRead"];
export type CreatedAccount = Schemas["CreatedAccountRead"];
export type GradingScale = Schemas["GradingScaleRead"];
export type NarrativeSection = Schemas["NarrativeSectionRead"];
export type NarrativeAssignment = Schemas["NarrativeAssignmentRead"];
export type Comment = Schemas["CommentRead"];
export type Checklist = Schemas["ChecklistRead"];
export type ClassPublication = Schemas["ClassPublicationRead"];
export type ReportState = Schemas["ReportStateRead"];
export type PublishOutcome = Schemas["PublishOutcomeRead"];
export type EntryEdit = Schemas["EntryEditRead"];
export type AuditPage = Schemas["AuditPageRead"];
export type AuditEntry = Schemas["AuditEntryRead"];
export type PupilEntries = Schemas["PupilEntriesRead"];
export type CorrectableRow = Schemas["CorrectableRowRead"];
export type ChecklistItem = Schemas["ChecklistItemRead"];
export type TermHalf = AssessmentPeriod["half"];
export type Role = Account["role"];

export function adminApi(token: string) {
  const get = <T>(path: string, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>(path, { token, query });
  const send = <T>(method: "POST" | "PUT" | "PATCH", path: string, body?: unknown) =>
    request<T>(path, { method, token, body });
  // D121: refused with a 409 that says what is in the way, while anything
  // depends on the record.
  const remove = (path: string) => request<void>(path, { method: "DELETE", token });

  return {
    /* --- Calendar ---------------------------------------------------- */
    sessions: () => get<AcademicSession[]>("/sessions"),
    createSession: (body: Schemas["AcademicSessionCreate"]) =>
      send<AcademicSession>("POST", "/sessions", body),
    updateSession: (id: string, body: Schemas["AcademicSessionUpdate"]) =>
      send<AcademicSession>("PATCH", `/sessions/${id}`, body),
    deleteSession: (id: string) => remove(`/sessions/${id}`),
    makeSessionCurrent: (id: string) =>
      send<AcademicSession>("POST", `/sessions/${id}/current`),

/* --- Publication and the audit log (§7, R12, R13) ------------------ */

    publication: (classId: string, termId: string) =>
      get<ClassPublication>(`/classes/${classId}/publication`, { term_id: termId }),

    publishClass: (
      classId: string,
      termId: string,
      body: Schemas["PublishRequest"],
    ) =>
      request<PublishOutcome>(`/classes/${classId}/publish`, {
        method: "POST",
        token,
        query: { term_id: termId },
        body,
      }),

    releaseReport: (reportId: string) =>
      send<ReportState>("POST", `/reports/${reportId}/release`),

    withholdReport: (reportId: string, reason: string) =>
      send<ReportState>("POST", `/reports/${reportId}/withhold`, { reason }),

    /** The printable card (§9), as a blob URL the browser can open.
     *
     *  Not a plain link: the endpoint needs an Authorization header and a
     *  browser following an anchor sends none. `fetch` carries the header,
     *  follows the 302 to the signed URL itself, and hands back the PDF —
     *  which is then a blob the viewer or the print dialog can take.
     */
    cardBlobUrl: (pupilId: string, termId: string, half: "first_half" | "second_half") =>
      requestBlob(`/pupils/${pupilId}/card`, { token, query: { term_id: termId, half } }),

    /** The ids `editEntry` needs — §7 lists the PATCH and no way to reach
     *  one (D75). */
    pupilEntries: (pupilId: string, termId: string) =>
      get<PupilEntries>(`/pupils/${pupilId}/entries`, { term_id: termId }),

    /** R13: a reason is required, and the grade is re-resolved against the
     *  scale the row was frozen against, never today's. */
    editEntry: (entryId: string, body: Schemas["EntryEditRequest"]) =>
      send<EntryEdit>("PATCH", `/entries/${entryId}`, body),

    audit: (query: {
      entity_type?: string;
      entity_id?: string;
      action?: string;
      limit?: number;
      offset?: number;
    }) => get<AuditPage>("/audit", query),

        terms: (academicSessionId?: string) =>
      get<Term[]>("/terms", { academic_session_id: academicSessionId }),
    createTerm: (body: Schemas["TermCreate"]) => send<Term>("POST", "/terms", body),
    updateTerm: (id: string, body: Schemas["TermUpdate"]) =>
      send<Term>("PATCH", `/terms/${id}`, body),
    makeTermCurrent: (id: string) => send<Term>("POST", `/terms/${id}/current`),
    deleteTerm: (id: string) => remove(`/terms/${id}`),

    assessmentPeriods: (termId: string) =>
      get<AssessmentPeriod[]>(`/terms/${termId}/assessment-periods`),
    saveAssessmentPeriod: (termId: string, body: Schemas["AssessmentPeriodSave"]) =>
      send<AssessmentPeriod>("POST", `/terms/${termId}/assessment-periods`, body),

    marksObtainable: (periodId: string) =>
      get<MarksObtainable[]>(`/assessment-periods/${periodId}/marks-obtainable`),
    saveMarksObtainable: (periodId: string, body: Schemas["MarksObtainableSave"]) =>
      send<MarksObtainable>("PUT", `/assessment-periods/${periodId}/marks-obtainable`, body),

    /* --- Classes and subjects ---------------------------------------- */
    classes: (includeInactive = false) =>
      get<SchoolClass[]>("/classes", { include_inactive: includeInactive }),
    createClass: (body: Schemas["ClassCreate"]) => send<SchoolClass>("POST", "/classes", body),
    updateClass: (id: string, body: Schemas["ClassUpdate"]) =>
      send<SchoolClass>("PATCH", `/classes/${id}`, body),
    deleteClass: (id: string) => remove(`/classes/${id}`),

    houses: () => get<House[]>("/houses"),
    createHouse: (body: Schemas["HouseCreate"]) => send<House>("POST", "/houses", body),
    updateHouse: (id: string, body: Schemas["HouseUpdate"]) =>
      send<House>("PATCH", `/houses/${id}`, body),
    deleteHouse: (id: string) => remove(`/houses/${id}`),

    subjects: (includeInactive = false) =>
      get<Subject[]>("/subjects", { include_inactive: includeInactive }),
    createSubject: (body: Schemas["SubjectCreate"]) => send<Subject>("POST", "/subjects", body),
    updateSubject: (id: string, body: Schemas["SubjectUpdate"]) =>
      send<Subject>("PATCH", `/subjects/${id}`, body),
    deleteSubject: (id: string) => remove(`/subjects/${id}`),

    classSubjects: (classId: string) => get<ClassSubject[]>(`/classes/${classId}/subjects`),
    setClassSubjects: (classId: string, subjectIds: string[]) =>
      send<ClassSubject[]>("PUT", `/classes/${classId}/subjects`, { subject_ids: subjectIds }),
    setSubjectTeacher: (classSubjectId: string, teacherUserId: string) =>
      send<Schemas["TeachingAssignmentRead"]>(
        "PUT",
        `/class-subjects/${classSubjectId}/teacher`,
        { teacher_user_id: teacherUserId },
      ),
    classTeacher: (classId: string) =>
      get<Schemas["ClassTeacherRead"] | null>(`/classes/${classId}/class-teacher`),
    setClassTeacher: (classId: string, teacherUserId: string) =>
      send<Schemas["ClassTeacherRead"]>("PUT", `/classes/${classId}/class-teacher`, {
        teacher_user_id: teacherUserId,
      }),

    /* --- People ------------------------------------------------------- */
    pupils: (query: {
      class_id?: string;
      search?: string;
      include_inactive?: boolean;
      pending?: boolean;
      limit?: number;
      offset?: number;
    }) =>
      get<PupilPage>("/pupils", query),
    createPupil: (body: Schemas["PupilCreate"]) => send<Pupil>("POST", "/pupils", body),
    updatePupil: (id: string, body: Schemas["PupilUpdate"]) =>
      send<Pupil>("PATCH", `/pupils/${id}`, body),
    deletePupil: (id: string) => remove(`/pupils/${id}`),
    approvePupil: (id: string) => send<Pupil>("POST", `/pupils/${id}/approve`),
    setEnrollment: (pupilId: string, body: Schemas["EnrollmentSave"]) =>
      send<Schemas["EnrollmentRead"]>("PUT", `/pupils/${pupilId}/enrollment`, body),

    users: (role?: Role) => get<Account[]>("/users", { role }),
    /** Parents who signed themselves up and wait for approval (D126). */
    pendingUsers: () => get<Account[]>("/users", { pending: true }),
    approveUser: (id: string) => send<Account>("POST", `/users/${id}/approve`),
    rejectUser: (id: string) => send<{ detail: string }>("POST", `/users/${id}/reject`),
    createUser: (body: Schemas["UserCreate"]) => send<CreatedAccount>("POST", "/users", body),
    updateUser: (id: string, body: Schemas["UserUpdate"]) =>
      send<Account>("PATCH", `/users/${id}`, body),
    deleteUser: (id: string) => remove(`/users/${id}`),
    resetPassword: (id: string) =>
      send<CreatedAccount>("POST", `/users/${id}/reset-password`),

    children: (guardianId: string) => get<Pupil[]>(`/guardians/${guardianId}/children`),
    linkChildren: (guardianId: string, body: Schemas["GuardianChildrenSave"]) =>
      send<Pupil[]>("POST", `/guardians/${guardianId}/children`, body),

    /* --- Assessment configuration ------------------------------------ */
    gradingScales: () => get<GradingScale[]>("/grading-scales"),
    deleteGradingScale: (id: string) => remove(`/grading-scales/${id}`),
    createGradingScale: (body: Schemas["GradingScaleCreate"]) =>
      send<GradingScale>("POST", "/grading-scales", body),
    activateGradingScale: (id: string) =>
      send<GradingScale>("POST", `/grading-scales/${id}/activate`),

    narrativeSections: () => get<NarrativeSection[]>("/narrative-sections"),
    saveNarrativeSections: (body: Schemas["NarrativeSectionsSave"]) =>
      send<NarrativeSection[]>("PUT", "/narrative-sections", body),
    createNarrativeSection: (body: Schemas["NarrativeSectionCreate"]) =>
      send<NarrativeSection>("POST", "/narrative-sections", body),
    deleteNarrativeSection: (id: string) => remove(`/narrative-sections/${id}`),

    narrativeAssignments: (classId: string) =>
      get<NarrativeAssignment[]>(`/classes/${classId}/narrative-assignments`),
    setNarrativeAssignments: (classId: string, body: Schemas["NarrativeAssignmentsSave"]) =>
      send<NarrativeAssignment[]>("PUT", `/classes/${classId}/narrative-assignments`, body),

    comments: (scope?: string) => get<Comment[]>("/comment-bank", { scope }),
    updateComment: (id: string, body: Schemas["CommentUpdate"]) =>
      send<Comment>("PATCH", `/comment-bank/${id}`, body),
    deleteComment: (id: string) => remove(`/comment-bank/${id}`),
    createComment: (body: Schemas["CommentCreate"]) =>
      send<Comment>("POST", "/comment-bank", body),

    /* --- Readiness ---------------------------------------------------- */
    checklist: (termId: string) => get<Checklist>("/setup-checklist", { term_id: termId }),
  };
}

export type AdminApi = ReturnType<typeof adminApi>;
