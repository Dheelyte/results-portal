/**
 * The admin setup surface of ARCHITECTURE.md §7, as typed functions.
 *
 * One function per endpoint, named after what the admin is doing rather than
 * after the HTTP verb. Types are the generated ones throughout; this file
 * adds no shapes of its own.
 */

import { request, type Schemas } from "./client";

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
export type ChecklistItem = Schemas["ChecklistItemRead"];
export type TermHalf = AssessmentPeriod["half"];
export type Role = Account["role"];

export function adminApi(token: string) {
  const get = <T>(path: string, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>(path, { token, query });
  const send = <T>(method: "POST" | "PUT" | "PATCH", path: string, body?: unknown) =>
    request<T>(path, { method, token, body });

  return {
    /* --- Calendar ---------------------------------------------------- */
    sessions: () => get<AcademicSession[]>("/sessions"),
    createSession: (body: Schemas["AcademicSessionCreate"]) =>
      send<AcademicSession>("POST", "/sessions", body),
    makeSessionCurrent: (id: string) =>
      send<AcademicSession>("POST", `/sessions/${id}/current`),

    terms: (academicSessionId?: string) =>
      get<Term[]>("/terms", { academic_session_id: academicSessionId }),
    createTerm: (body: Schemas["TermCreate"]) => send<Term>("POST", "/terms", body),
    updateTerm: (id: string, body: Schemas["TermUpdate"]) =>
      send<Term>("PATCH", `/terms/${id}`, body),
    makeTermCurrent: (id: string) => send<Term>("POST", `/terms/${id}/current`),

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

    houses: () => get<House[]>("/houses"),
    createHouse: (body: Schemas["HouseCreate"]) => send<House>("POST", "/houses", body),

    subjects: (includeInactive = false) =>
      get<Subject[]>("/subjects", { include_inactive: includeInactive }),
    createSubject: (body: Schemas["SubjectCreate"]) => send<Subject>("POST", "/subjects", body),
    updateSubject: (id: string, body: Schemas["SubjectUpdate"]) =>
      send<Subject>("PATCH", `/subjects/${id}`, body),

    classSubjects: (classId: string) => get<ClassSubject[]>(`/classes/${classId}/subjects`),
    setClassSubjects: (classId: string, subjectIds: string[]) =>
      send<ClassSubject[]>("PUT", `/classes/${classId}/subjects`, { subject_ids: subjectIds }),
    setSubjectTeacher: (classSubjectId: string, teacherUserId: string) =>
      send<Schemas["TeachingAssignmentRead"]>(
        "PUT",
        `/class-subjects/${classSubjectId}/teacher`,
        { teacher_user_id: teacherUserId },
      ),
    setClassTeacher: (classId: string, teacherUserId: string) =>
      send<Schemas["ClassTeacherRead"]>("PUT", `/classes/${classId}/class-teacher`, {
        teacher_user_id: teacherUserId,
      }),

    /* --- People ------------------------------------------------------- */
    pupils: (query: { class_id?: string; search?: string; limit?: number; offset?: number }) =>
      get<PupilPage>("/pupils", query),
    createPupil: (body: Schemas["PupilCreate"]) => send<Pupil>("POST", "/pupils", body),
    setEnrollment: (pupilId: string, body: Schemas["EnrollmentSave"]) =>
      send<Schemas["EnrollmentRead"]>("PUT", `/pupils/${pupilId}/enrollment`, body),

    users: (role?: Role) => get<Account[]>("/users", { role }),
    createUser: (body: Schemas["UserCreate"]) => send<CreatedAccount>("POST", "/users", body),
    resetPassword: (id: string) =>
      send<CreatedAccount>("POST", `/users/${id}/reset-password`),

    children: (guardianId: string) => get<Pupil[]>(`/guardians/${guardianId}/children`),
    linkChildren: (guardianId: string, body: Schemas["GuardianChildrenSave"]) =>
      send<Pupil[]>("POST", `/guardians/${guardianId}/children`, body),

    /* --- Assessment configuration ------------------------------------ */
    gradingScales: () => get<GradingScale[]>("/grading-scales"),
    createGradingScale: (body: Schemas["GradingScaleCreate"]) =>
      send<GradingScale>("POST", "/grading-scales", body),
    activateGradingScale: (id: string) =>
      send<GradingScale>("POST", `/grading-scales/${id}/activate`),

    narrativeSections: () => get<NarrativeSection[]>("/narrative-sections"),
    saveNarrativeSections: (body: Schemas["NarrativeSectionsSave"]) =>
      send<NarrativeSection[]>("PUT", "/narrative-sections", body),

    narrativeAssignments: (classId: string) =>
      get<NarrativeAssignment[]>(`/classes/${classId}/narrative-assignments`),
    setNarrativeAssignments: (classId: string, body: Schemas["NarrativeAssignmentsSave"]) =>
      send<NarrativeAssignment[]>("PUT", `/classes/${classId}/narrative-assignments`, body),

    comments: (scope?: string) => get<Comment[]>("/comment-bank", { scope }),
    createComment: (body: Schemas["CommentCreate"]) =>
      send<Comment>("POST", "/comment-bank", body),

    /* --- Readiness ---------------------------------------------------- */
    checklist: (termId: string) => get<Checklist>("/setup-checklist", { term_id: termId }),
  };
}

export type AdminApi = ReturnType<typeof adminApi>;
