// Frontend names for the backend's API types.
//
// The shapes come from `api.generated.ts`, which is generated from the FastAPI app's own OpenAPI schema
// (`npm run types:generate`), so they are never a hand-maintained copy of the Pydantic models.
//
// Pydantic fields with defaults appear as optional in the schema, but FastAPI always serialises every field
// in a response. `Wire<T>` therefore marks every property of a *response* type as present (its value can still
// be `null` where the schema allows it). Request bodies use the schema as-is.
import type { components } from './api.generated'

type Schemas = components['schemas']

export type Wire<T> = T extends (infer U)[]
  ? Wire<U>[]
  : T extends object
    ? { [K in keyof T]-?: Wire<Exclude<T[K], undefined>> }
    : T

type Response<N extends keyof Schemas> = Wire<Schemas[N]>

// --------------------------------------------------------------------------- auth
export type User = Response<'UserOut'>
export type AuthResponse = Response<'AuthResponse'>

// --------------------------------------------------------------------------- resumes and quality analysis
export type ResumeSummary = Response<'ResumeSummary'>
export type ResumeDetail = Response<'ResumeDetail'>
export type StructuredResume = Response<'StructuredResume'>
export type TextField = Response<'TextField'>
export type QualityReport = Response<'QualityReport'>
export type DimensionScore = Response<'DimensionScore'>
export type QualityRecommendation = Response<'Recommendation'>

// --------------------------------------------------------------------------- legacy combined reviews (/api/analyze)
export type AnalysisRecord = Response<'AnalysisRecord'>
export type AnalysisListItem = Response<'AnalysisListItem'>

// --------------------------------------------------------------------------- jobs and matching
export type JobSummary = Response<'JobSummary'>
export type JobDetail = Response<'JobDetail'>
export type JobRequirement = Response<'JobRequirement'>
export type MatchSummary = Response<'MatchSummary'>
export type MatchDetail = Response<'MatchDetail'>
export type MatchReport = Response<'MatchReport'>
export type RequirementResult = Response<'RequirementResult'>
export type SkillRef = Response<'SkillRef'>

// --------------------------------------------------------------------------- rewrites, verification and exports
export type ResumeDocument = Response<'ResumeDocument'>
export type RewriteSummary = Response<'RewriteSummary'>
export type RewriteDetail = Response<'RewriteDetail'>
export type VersionSummary = Response<'VersionSummary'>
export type Suggestion = Response<'Suggestion'>
export type SuggestionVerification = Response<'SuggestionVerification'>
export type VerificationSummary = Response<'VerificationSummary'>
export type VerificationIssue = Response<'VerificationIssue'>
export type GenerationInfo = Response<'GenerationInfo'>
export type ScoreComparison = Response<'ScoreComparison'>
export type TemplateInfo = Response<'TemplateInfo'>
export type PreviewResponse = Response<'PreviewResponse'>

export type RewriteScope = Schemas['RewriteCreate']['scope']
export type RewriteMode = NonNullable<Schemas['RewriteCreate']['mode']>
export type TemplateKey = Schemas['TemplateInfo']['key']
export type ExportFormat = Schemas['ExportRequest']['format']
export type SuggestionDecision = 'accepted' | 'rejected'

// Request bodies (sent as-is).
export type RewriteCreateRequest = Schemas['RewriteCreate']
export type RewriteUpdateChanges = Omit<Schemas['RewriteUpdate'], 'base_version'>

// --------------------------------------------------------------------------- error envelope
/** Every error response: `{ detail, error: { code, message, request_id } }` (see backend app/core/errors.py). */
export interface ErrorEnvelope {
  detail?: string
  error?: { code?: string; message?: string; request_id?: string; fields?: { loc: string[]; msg: string }[] }
}
