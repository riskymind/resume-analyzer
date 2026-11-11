// API-shaped test data, typed against the types generated from the backend's OpenAPI schema: if the API changes
// shape, these fixtures stop compiling instead of silently testing an outdated contract. Builders return fresh
// copies. All names, employers and contact details are invented.
import type {
  AnalysisListItem,
  AnalysisRecord,
  JobDetail,
  JobSummary,
  MatchDetail,
  MatchReport,
  MatchSummary,
  QualityReport,
  ResumeDetail,
  ResumeDocument,
  ResumeSummary,
  RewriteDetail,
  RewriteSummary,
  ScoreComparison,
  Suggestion,
  TemplateInfo,
  TextField,
  User,
  VerificationIssue,
  VerificationSummary,
  GenerationInfo,
} from '../types/api'

export const USER: User = { id: 'user-1', email: 'jane@example.com', created_at: '2026-10-01T09:00:00Z' }

export const AUTH = { user: USER, csrf_token: 'csrf-test-token' }

export const RESUMES: ResumeSummary[] = [
  {
    id: 'res-1',
    filename: 'jane-doe.md',
    file_format: 'md',
    created_at: '2026-11-01T10:00:00Z',
    overall_score: 70,
    ats_score: 82,
    label: 'Good',
  },
  {
    id: 'res-2',
    filename: 'old-cv.pdf',
    file_format: 'pdf',
    created_at: '2026-10-01T10:00:00Z',
    overall_score: 55,
    ats_score: 60,
    label: 'Fair',
  },
]

const text = (value: string | null, status: TextField['status'] = value ? 'explicit' : 'missing'): TextField => ({
  value,
  status,
  evidence: null,
})

export function qualityReport(overrides: Partial<QualityReport> = {}): QualityReport {
  return {
    scoring_version: 'quality/1',
    overall_score: 70,
    label: 'Good',
    ats_score: 82,
    ats_checks: [
      {
        code: 'tables',
        passed: false,
        points: 5,
        message: 'Tables may not be read correctly.',
        recommendation: 'Use plain text.',
      },
    ],
    dimensions: [
      {
        key: 'achievements',
        label: 'Achievements',
        weight: 20,
        score: 45,
        contribution: 9,
        deductions: [
          {
            code: 'few_metrics',
            points: 30,
            message: 'Few bullets include results.',
            recommendation: 'Add outcomes where you have them.',
            evidence: null,
          },
        ],
        strengths: [],
      },
      {
        key: 'contact',
        label: 'Contact details',
        weight: 10,
        score: 100,
        contribution: 10,
        deductions: [],
        strengths: ['Email present.'],
      },
    ],
    strengths: ['Clear section headings.'],
    weaknesses: ['Most bullets describe duties rather than results.'],
    missing_information: ['No professional summary.'],
    recommendations: [
      {
        dimension: 'achievements',
        message: 'Few bullets include results.',
        recommendation: 'Describe the outcome of your work.',
        impact: 6,
      },
    ],
    metrics: {
      word_count: 320,
      bullet_count: 8,
      quantified_bullet_ratio: 0.25,
      action_verb_ratio: 0.6,
      reading_ease: 52,
      experience_entries: 2,
      technical_skill_count: 6,
    },
    score_cap: null,
    disclaimer: 'The ATS compatibility score estimates how reliably automated applicant tracking systems can read it.',
    ...overrides,
  }
}

export function resumeDetail(overrides: Partial<ResumeDetail> = {}): ResumeDetail {
  const summary = RESUMES[0] as ResumeSummary
  return {
    ...summary,
    page_count: null,
    warnings: [],
    sections: [
      { kind: 'experience', heading: 'Experience' },
      { kind: 'education', heading: 'Education' },
    ],
    text: '# Jane Doe',
    structured: {
      contact: {
        name: text('Jane Doe'),
        email: text('jane@example.com'),
        phone: text(null),
        location: text(null),
        links: [],
      },
      summary: text(null),
      experience: [],
      education: [],
      technical_skills: [{ name: 'Python', status: 'explicit', evidence: null }],
      soft_skills: [],
      certifications: [],
      projects: [],
      languages: [],
      extraction: { method: 'ai', provider: 'fake', prompt_version: 'test', removed_items: 0, warnings: [] },
    },
    quality: qualityReport(),
    ...overrides,
  }
}

export const JOBS: JobSummary[] = [
  {
    id: 'job-1',
    title: 'Senior Backend Engineer',
    company: 'Globex',
    source: 'pasted',
    source_format: 'text',
    created_at: '2026-11-02T10:00:00Z',
    requirement_count: 3,
    match_count: 1,
  },
]

export function job(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    ...(JOBS[0] as JobSummary),
    text: 'Senior Backend Engineer at Globex. Python required.',
    info: {
      title: text('Senior Backend Engineer'),
      company: text('Globex'),
      location: text(null),
      work_arrangement: text(null),
      employment_type: text(null),
      seniority: text(null),
    },
    requirements: [
      {
        id: 'r1',
        name: 'Python',
        category: 'technical_skill',
        classification: 'required',
        classification_source: 'text',
        importance: 'high',
        evidence: 'Python required',
        status: 'verified',
        min_years: null,
        alternative_group: null,
      },
    ],
    keywords: [],
    extraction: {
      method: 'ai+verification',
      provider: 'fake',
      prompt_version: 'test',
      removed_items: 0,
      reclassified_items: 0,
      detected_items: 0,
      warnings: [],
    },
    warnings: [],
    ...overrides,
  }
}

export const MATCHES: MatchSummary[] = [
  {
    id: 'match-1',
    resume_id: 'res-1',
    job_id: 'job-1',
    resume_filename: 'jane-doe.md',
    job_title: 'Senior Backend Engineer',
    match_score: 64,
    label: 'Good Match',
    semantic_status: 'available',
    matching_version: 'match/1',
    created_at: '2026-11-03T10:00:00Z',
  },
]

export function matchReport(overrides: Partial<MatchReport> = {}): MatchReport {
  const python = {
    requirement_id: 'r1',
    name: 'Python',
    classification: 'required' as const,
    category: 'technical_skill' as const,
    resume_term: null,
  }
  return {
    matching_version: 'match/1',
    match_score: 64,
    label: 'Good Match',
    classification: 'A reasonable match with some gaps.',
    score_cap: null,
    components: [
      {
        key: 'required_skills',
        label: 'Required skills',
        weight: 40,
        effective_weight: 50,
        score: 80,
        contribution: 40,
        requirement_ids: ['r1'],
      },
    ],
    requirements: [
      {
        requirement_id: 'r1',
        name: 'Python',
        category: 'technical_skill',
        classification: 'required',
        importance: 'high',
        jd_evidence: 'Python required',
        status: 'matched',
        match_type: 'exact',
        credit: 1,
        weight: 1,
        component: 'required_skills',
        evidence: [{ section: 'skills', label: null, text: 'Python' }],
        related_to: null,
        similarity: null,
        candidate_years: null,
        required_years: null,
        alternative_group: null,
        counted: true,
        satisfied_by_alternative: null,
        explanation: 'Python is listed in your skills.',
      },
    ],
    skills: { exact: [python], related: [], missing: [], required_total: 1, preferred_total: 0 },
    experience: {
      candidate_years: 6,
      stated_years: 6,
      required_years: 5,
      relevant_roles: [],
      gaps: [],
      responsibility_alignment: null,
      seniority: { job_level: 'senior', resume_level: 'senior', status: 'aligned', explanation: 'Levels match.' },
    },
    qualifications: {
      education_matched: [],
      education_missing: [],
      certifications_matched: [],
      certifications_missing: [],
    },
    keywords: { present: ['python'], missing: ['terraform'], coverage: 50 },
    recommendations: {
      top: [{ kind: 'keyword', requirement_id: null, message: 'Mention Terraform if you have used it.', impact: 3 }],
      skills_to_develop: [],
      present_better: [],
      missing_evidence: [],
    },
    semantic: { status: 'available', model: 'embed', reason: null, related_threshold: 0.8, text_threshold: 0.7 },
    confidence: { level: 'high', evidence_coverage: 100, reasons: [] },
    methodology: {
      version: 'match/1',
      formula: 'Weighted sum of component scores.',
      weights: {},
      credits: {},
      thresholds: {},
      notes: [],
    },
    warnings: [],
    disclaimer: 'This match does not predict any hiring decision.',
    ...overrides,
  }
}

export function matchDetail(overrides: Partial<MatchDetail> = {}): MatchDetail {
  return { ...(MATCHES[0] as MatchSummary), report: matchReport(), ...overrides }
}

export const ANALYSES: AnalysisListItem[] = [
  { id: 7, created_at: '2026-10-20T10:00:00Z', resume_filename: 'quick-cv.pdf', score: 58, score_label: 'Fair Match' },
]

export function analysisRecord(overrides: Partial<AnalysisRecord> = {}): AnalysisRecord {
  return {
    id: 7,
    created_at: '2026-10-20T10:00:00Z',
    resume_filename: 'quick-cv.pdf',
    jd_source: 'pasted',
    result: {
      score: 58,
      score_label: 'Fair Match',
      recommendations: {
        missing_keywords: ['Terraform'],
        phrasing_suggestions: [],
        skill_gaps: [],
        formatting_notes: [],
      },
    },
    resume_id: null,
    resume_quality: null,
    job_match_id: null,
    ...overrides,
  }
}

export const TEMPLATES: TemplateInfo[] = [
  { key: 'modern', name: 'Modern professional', description: 'Clean sans-serif layout.' },
  { key: 'minimal', name: 'Minimalist', description: 'Black and white.' },
  { key: 'corporate', name: 'Traditional corporate', description: 'Serif typography.' },
  { key: 'technical', name: 'Technical', description: 'Skills first, then experience and projects.' },
  { key: 'graduate', name: 'Graduate', description: 'Education and coursework first.' },
]

export function documentContent(overrides: Partial<ResumeDocument> = {}): ResumeDocument {
  return {
    contact: { name: 'Jane Doe', email: 'jane@example.com', phone: null, location: null, links: [] },
    summary: 'Backend engineer with 6 years of experience building Python APIs.',
    experience: [
      {
        id: 'exp-1',
        title: 'Senior Software Engineer',
        employer: 'Acme Corp',
        location: null,
        start_date: '2021',
        end_date: 'Present',
        bullets: [
          {
            id: 'exp-1-b1',
            text: 'Led migration of 40 services to Kubernetes, cutting deploy time by 35%.',
            source_ids: ['exp-1-b1'],
          },
          { id: 'exp-1-b2', text: 'Built FastAPI services handling 2M requests per day.', source_ids: ['exp-1-b2'] },
        ],
      },
    ],
    education: [
      {
        id: 'edu-1',
        institution: 'State University',
        qualification: 'BSc',
        field_of_study: 'Computer Science',
        start_date: null,
        end_date: '2018',
        grade: null,
        coursework: [],
      },
    ],
    certifications: [],
    projects: [],
    technical_skills: ['Python', 'FastAPI', 'PostgreSQL'],
    soft_skills: [],
    languages: [],
    ...overrides,
  }
}

export function suggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 'g1-s1',
    unit: 'summary',
    section: 'summary',
    item_id: null,
    kind: 'text',
    original: 'Backend engineer with 6 years of experience building Python APIs.',
    proposed: 'Backend engineer with 6 years of experience designing Python APIs.',
    source_ids: [],
    technical: null,
    soft: null,
    order: null,
    rationale: 'Stronger verb.',
    keywords: [],
    requirement_ids: [],
    metric_prompt: null,
    verification: { status: 'verified', issues: [] },
    decision: 'pending',
    auto_rejected: false,
    generation: 1,
    ...overrides,
  }
}

export const VERIFIED: VerificationSummary = {
  status: 'verified',
  blocking: 0,
  warnings: 0,
  issues: [],
  rejected_suggestions: 0,
  pending_review: 0,
  checks: ['Every number must appear in the original text it rewrites.'],
}

export function unsupportedVerification(issues?: VerificationIssue[]): VerificationSummary {
  const list: VerificationIssue[] = issues || [
    {
      code: 'unsupported_skill',
      severity: 'blocking',
      message: '“Terraform” is not mentioned anywhere in your original resume.',
      term: 'Terraform',
      unit: 'summary',
      item_id: null,
      origin: 'user',
      action: 'flagged',
    },
  ]
  return {
    ...VERIFIED,
    status: list.some((i) => i.severity === 'blocking') ? 'unsupported' : 'needs_review',
    blocking: list.filter((i) => i.severity === 'blocking').length,
    warnings: list.filter((i) => i.severity === 'warning').length,
    issues: list,
  }
}

export function scores(overrides: Partial<ScoreComparison> = {}): ScoreComparison {
  return {
    quality: {
      before: 70,
      after: 74,
      before_ats: 80,
      after_ats: 82,
      before_label: 'Good',
      after_label: 'Good',
      uploaded_score: 70,
    },
    match: {
      job_id: 'job-1',
      job_title: 'Senior Backend Engineer',
      before: 61,
      after: 66,
      before_label: 'Fair',
      after_label: 'Good',
      newly_evidenced: [],
      still_missing: ['Terraform'],
      saved_match_score: 60,
      method: 'Deterministic requirement matching.',
    },
    keywords_incorporated: [],
    disclaimer: 'Scores do not guarantee an interview.',
    ...overrides,
  }
}

export function generation(overrides: Partial<GenerationInfo> = {}): GenerationInfo {
  return {
    generation: 1,
    scope: 'full',
    mode: 'job_targeted',
    bullet_ids: [],
    provider: 'gemini',
    prompt_version: 'resume-rewrite/1',
    alignment_notes: [],
    gaps: [],
    metric_prompts: [],
    discarded_items: 0,
    warnings: [],
    ...overrides,
  }
}

/** A rewrite detail (GET /v1/rewrites/{id}). `version` defaults to the current version. */
export function rewriteDetail(overrides: Partial<RewriteDetail> = {}): RewriteDetail {
  const current = overrides.current_version ?? 1
  const versions =
    overrides.versions ??
    Array.from({ length: current }, (_, index) => ({
      number: current - index,
      source: current - index === 1 ? ('generate' as const) : ('edit' as const),
      created_at: '2026-11-09T10:00:00Z',
      quality_after: 74,
      match_after: 66,
      verification_status: 'verified',
    }))
  return {
    id: 'rw-1',
    name: 'jane-doe – Senior Backend Engineer',
    resume_id: 'res-1',
    resume_filename: 'jane-doe.md',
    job_id: 'job-1',
    job_title: 'Senior Backend Engineer',
    mode: 'job_targeted',
    template: 'modern',
    current_version: current,
    quality_before: 70,
    quality_after: 74,
    match_before: 61,
    match_after: 66,
    verification_status: 'verified',
    job_detached_at: null,
    created_at: '2026-11-09T10:00:00Z',
    updated_at: '2026-11-09T10:00:00Z',
    version: current,
    original: documentContent(),
    content: documentContent(),
    suggestions: [suggestion()],
    verification: VERIFIED,
    scores: scores(),
    generation: generation(),
    ...overrides,
    versions,
  }
}

/** The list-row shape of a rewrite (GET /v1/rewrites). */
export function summaryOf(detail: RewriteDetail): RewriteSummary {
  return {
    id: detail.id,
    name: detail.name,
    resume_id: detail.resume_id,
    resume_filename: detail.resume_filename,
    job_id: detail.job_id,
    job_title: detail.job_title,
    mode: detail.mode,
    template: detail.template,
    current_version: detail.current_version,
    quality_before: detail.quality_before,
    quality_after: detail.quality_after,
    match_before: detail.match_before,
    match_after: detail.match_after,
    verification_status: detail.verification_status,
    job_detached_at: detail.job_detached_at,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  }
}
