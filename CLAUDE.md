# PROJECT: Resume Analyzer — Full-Stack Refactoring, AI Resume Optimization & Production Deployment

You are acting as a Senior Full-Stack Engineer, AI Engineer, Software Architect, DevOps Engineer, and UI/UX Engineer.

Your task is to thoroughly audit, refactor, improve, and productionize the existing repository:

Repository: https://github.com/riskymind/resume-analyzer.git

The objective is to transform the existing application into a modern, reliable, secure, AI-powered resume analysis and optimization platform.

This is an existing project. Do not blindly replace the codebase or start a new implementation. First understand the existing architecture, preserve useful functionality, identify technical debt, and refactor incrementally.

The final application must support deployment to:

1. Vercel
2. Render
3. Docker / Docker Compose

Do not commit, push, or deploy anything without explicit authorization.

---

# PHASE 1: COMPLETE CODEBASE AUDIT

Before making changes, inspect the entire repository.

Investigate:

- Existing directory structure.
- Frontend architecture and framework.
- Backend architecture and framework.
- API endpoints and integrations.
- AI/LLM integrations.
- Resume parsing and document extraction.
- Database configuration and data models.
- Authentication and authorization.
- File upload and storage implementation.
- Environment variable management.
- Existing tests.
- Dependency versions and vulnerabilities.
- Build configuration.
- Existing deployment configuration.
- Error handling and logging.
- Performance bottlenecks.
- Security vulnerabilities.

Identify:

1. What currently works.
2. What is partially implemented.
3. What is broken.
4. What needs refactoring.
5. What needs to be implemented.
6. What should be removed or replaced.

Create the following documentation:

- `docs/architecture-audit.md`
- `docs/refactoring-plan.md`
- `docs/deployment-architecture.md`

Do not begin a large-scale refactor until the audit and implementation plan are established.

Preserve the existing technology stack where it is appropriate. Only introduce new technologies when they provide a clear architectural advantage.

# PHASE 2: TARGET ARCHITECTURE

Refactor the application into a clean, modular, maintainable architecture.

Separate responsibilities into:

- Presentation layer.
- API/controller layer.
- Business logic/services.
- AI integration layer.
- Resume parsing layer.
- Database/repository layer.
- File storage layer.
- Authentication/security layer.
- Document generation layer.

Requirements:

- Strong typing wherever supported.
- Reusable components.
- Centralized configuration.
- Dependency injection where appropriate.
- Consistent API response structures.
- Centralized exception handling.
- Structured logging.
- Input validation.
- Separation of development and production configuration.
- No hardcoded secrets.
- No duplicated business logic.

Do not overengineer the application.

# PHASE 3: RESUME ANALYSIS ENGINE

Improve the existing resume analysis functionality.

Users should be able to upload resumes in:

- PDF
- DOCX

Implement robust document extraction.

Extract structured information such as:

- Full name.
- Professional summary.
- Contact information.
- Work experience.
- Education.
- Technical skills.
- Soft skills.
- Certifications.
- Projects.
- Achievements.
- Languages.

Handle malformed, empty, encrypted, and unsupported documents gracefully.

Build a resume analysis engine that evaluates:

1. Resume structure.
2. Content quality.
3. Professional summary.
4. Skills relevance.
5. Experience descriptions.
6. Achievement quality.
7. Formatting consistency.
8. ATS compatibility.
9. Keyword relevance.
10. Readability.

Return structured analysis results.

Include:

- Overall score.
- ATS compatibility score.
- Section-by-section scores.
- Strengths.
- Weaknesses.
- Missing information.
- Actionable recommendations.

Do not claim that an ATS score guarantees employment or successful screening.

# PHASE 4: JOB DESCRIPTION ANALYSIS & MATCHING

Introduce job-specific resume analysis.

Users should be able to paste a job description into the application.

The system should extract:

- Job title.
- Company name, when provided.
- Required qualifications.
- Preferred qualifications.
- Required technical skills.
- Soft skills.
- Experience requirements.
- Education requirements.
- Responsibilities.
- Important keywords.

Compare the extracted job requirements with the uploaded resume.

Generate:

- Job match percentage.
- Matching skills.
- Missing skills.
- Partially matching skills.
- Experience gaps.
- Qualification gaps.
- Missing keywords.
- Recommendations for improving the resume.

The matching engine should use a combination of:

- Deterministic keyword matching.
- Semantic similarity where appropriate.
- Structured LLM analysis.

Do not rely exclusively on an LLM to calculate numerical scores.

Make the scoring methodology transparent and consistent.

# PHASE 5: NEW FEATURE — AI RESUME REWRITER

This is a major feature and must be implemented end-to-end.

## User journey

1. User uploads their existing resume.
2. User pastes the proposed job description.
3. Application analyzes both documents.
4. User reviews the job match analysis.
5. User clicks "Rewrite My Resume".
6. AI generates a tailored resume.
7. User reviews and edits the rewritten resume.
8. User downloads the final document.

## AI rewriting requirements

The AI must rewrite the resume to align with the proposed job description.

Improve:

- Professional summary.
- Work experience descriptions.
- Achievement statements.
- Skills presentation.
- Relevant projects.
- Technical terminology.
- Keyword placement.
- Section organization.

Use professional, concise, achievement-oriented language.

Where the source contains measurable achievements, preserve the actual figures.

Where figures are absent, do not invent them.

## Critical integrity requirements

The AI must NEVER:

- Invent employment history.
- Invent employers.
- Invent job titles.
- Invent academic qualifications.
- Invent certifications.
- Invent skills the user does not possess.
- Fabricate achievements.
- Add fake metrics or percentages.
- Change employment dates.

It must preserve factual information from the original resume.

When a job requirement is missing from the resume, identify it as a gap rather than pretending the applicant possesses it.

Make all AI-generated content editable before export.

## Rewrite modes

Support:

1. ATS Optimization — improve compatibility and keyword alignment.
2. Professional Rewrite — improve clarity, grammar, and professional presentation.
3. Job-Specific Rewrite — tailor the resume to the supplied job description.
4. Executive Rewrite — use an appropriate senior-level professional writing style.

Allow users to regenerate individual sections without rewriting the entire resume.

Provide before-and-after comparisons.

# PHASE 6: DOWNLOADABLE RESUME GENERATION

Implement professional resume exports.

Required formats:

- PDF
- DOCX

Provide multiple professional templates:

1. Modern Professional.
2. Minimal ATS-Friendly.
3. Technical / Software Engineer.
4. Executive.
5. Graduate / Entry-Level.

Requirements:

- Consistent typography.
- Proper spacing.
- Clear section headings.
- Professional layout.
- Correct page breaks.
- Clickable email and website links where supported.
- Consistent bullet formatting.
- No overlapping content.
- No broken symbols.
- No unnecessary graphics in ATS-friendly templates.

The user must be able to:

- Preview the rewritten resume.
- Edit its content.
- Select a template.
- Download PDF.
- Download DOCX.

Generate documents on the server or through an appropriate document-generation service.

Ensure generated documents are downloadable using secure, predictable file-handling mechanisms.

Do not expose private file-storage paths or credentials.

# PHASE 7: USER EXPERIENCE AND FRONTEND

Improve the existing interface while preserving its useful visual identity.

Create a modern, polished, responsive experience.

Expected application sections:

## Dashboard

Display:

- Recent resume analyses.
- Saved resumes.
- Previous job matches.
- Resume improvement suggestions.
- Recent rewritten resumes.

## Resume Upload

Provide:

- Drag-and-drop upload.
- File selection.
- File validation.
- Upload progress.
- Clear error messages.

## Resume Analysis

Display:

- Overall resume score.
- ATS score.
- Skill analysis.
- Strengths.
- Weaknesses.
- Improvement recommendations.

## Job Matching

Provide:

- Job description input.
- Job requirements extraction.
- Match percentage.
- Skills comparison.
- Missing keyword analysis.

## AI Resume Rewriter

Provide:

- Rewrite controls.
- Rewrite modes.
- Before-and-after comparison.
- Editable resume sections.
- Regeneration of individual sections.
- Template selection.
- Document preview.
- PDF and DOCX downloads.

Ensure:

- Mobile responsiveness.
- Accessible components.
- Loading states.
- Empty states.
- Error states.
- Success feedback.
- Consistent design system.

Avoid unnecessary UI complexity.

# PHASE 8: BACKEND AND API DESIGN

Refactor or introduce clean API endpoints based on the existing architecture.

Expected capabilities include:

- Resume upload.
- Resume extraction.
- Resume analysis.
- Job description analysis.
- Job matching.
- Resume rewriting.
- Section regeneration.
- Resume editing.
- Resume export.
- Resume history.

Use consistent request and response schemas.

Implement:

- Request validation.
- File size restrictions.
- MIME-type validation.
- File signature validation.
- Rate limiting.
- Authentication where applicable.
- Authorization checks.
- Secure file handling.
- Request timeouts.
- AI provider error handling.
- API error responses.

Do not trust file extensions alone when validating uploads.

Never expose AI API keys to the frontend.

# PHASE 9: DATABASE AND STORAGE

Audit the existing database implementation before changing it.

Preserve the current database if it is suitable.

If persistence is missing or inadequate, introduce an appropriate database architecture.

Support:

- User profiles.
- Uploaded resumes.
- Extracted resume information.
- Resume analysis history.
- Job descriptions.
- Job match results.
- Rewritten resumes.
- Export metadata.

Use migrations and proper database indexes.

Ensure user data is isolated.

Do not store uploaded files directly in ephemeral application directories in production.

Use persistent object storage where required.

For local Docker development, provide a suitable persistent storage configuration.

Include data deletion functionality and an appropriate retention policy.

# PHASE 10: VERCEL DEPLOYMENT

Make the application compatible with Vercel.

Inspect the actual framework and select the correct deployment strategy.

Requirements:

- Correct build configuration.
- Correct production start/runtime configuration.
- Environment variables configured through Vercel.
- No hardcoded localhost URLs.
- Correct API routing.
- Secure server-side AI integrations.
- Correct frontend/backend communication.
- Production error handling.
- Appropriate function timeouts and execution limits.

If the backend requires persistent processes or workloads incompatible with Vercel Functions, separate it appropriately rather than forcing it into an unsuitable serverless architecture.

Document the Vercel deployment process in:

`docs/deploy-vercel.md`

# PHASE 11: RENDER DEPLOYMENT

Make the application deployable on Render.

Support the appropriate Render service types for the selected architecture.

Requirements:

- Production start command.
- Environment variables.
- Health-check endpoint.
- Persistent storage or external object storage.
- Database connection configuration.
- Correct port binding using the platform-provided PORT variable.
- Production logging.
- Graceful shutdown.
- Appropriate timeout handling.

Create or update:

`render.yaml`

Only use configuration supported by the selected Render services.

Document deployment in:

`docs/deploy-render.md`

# PHASE 12: DOCKER AND DOCKER COMPOSE

Provide a production-ready Docker setup.

Create or improve:

- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml`
- `.env.example`

Requirements:

- Multi-stage builds where appropriate.
- Minimal production images.
- Non-root execution.
- Dependency caching.
- Health checks.
- Environment-based configuration.
- Persistent volumes where needed.
- Graceful shutdown.
- Appropriate network configuration.

Docker Compose should support local development and production-like testing.

The application must start using a documented command similar to:

`docker compose up --build`

Do not bake secrets into Docker images.

# PHASE 13: SECURITY

Perform a security review.

Pay particular attention to:

- File upload vulnerabilities.
- Malicious document handling.
- Prompt injection through uploaded resumes and job descriptions.
- API key exposure.
- Authentication and authorization.
- Cross-origin configuration.
- SQL injection.
- Path traversal.
- SSRF.
- Excessive AI API usage.
- Rate limiting.
- Sensitive information in logs.
- Temporary file cleanup.
- Unauthorized access to generated documents.

Treat uploaded resumes and job descriptions as untrusted data, not instructions for the AI system.

Apply least-privilege principles.

# PHASE 14: TESTING AND QUALITY ASSURANCE

Create or improve automated tests.

Include:

## Unit tests

- Resume parsing.
- Resume extraction.
- Resume scoring.
- Job description extraction.
- Job matching.
- AI rewrite validation.
- Document generation.
- File validation.

## Integration tests

- Resume upload API.
- Resume analysis API.
- Job matching API.
- Resume rewriting API.
- PDF export.
- DOCX export.

## Security tests

- Invalid file uploads.
- Oversized files.
- Unauthorized access.
- Malformed requests.
- Cross-user data access.
- Prompt injection handling.

## Frontend tests

- Resume upload flow.
- Analysis results.
- Job matching.
- Resume rewriting.
- Editing.
- Downloads.

Mock external AI providers in automated tests.

Do not consume real AI API credits during normal test execution.

Before declaring completion, run:

- Dependency installation.
- Type checking.
- Linting.
- Unit tests.
- Integration tests.
- Production builds.
- Docker build.
- Docker Compose startup verification.

Fix all regressions introduced by the refactoring.

# PHASE 15: ENVIRONMENT CONFIGURATION

Create a complete `.env.example`.

Document every environment variable.

Separate public frontend variables from private server-side variables.

Include only variables actually required by the implemented architecture.

Examples of possible configuration categories:

- Application environment.
- Frontend URL.
- Backend URL.
- Database URL.
- AI provider API keys.
- Authentication secrets.
- Storage credentials.
- CORS origins.
- Upload size limits.
- Rate limiting.
- Logging configuration.

Never commit actual secrets.

Ensure missing required environment variables produce clear startup errors.

# PHASE 16: CI/CD

Introduce GitHub Actions if appropriate.

Create workflows for:

- Dependency installation.
- Linting.
- Type checking.
- Automated testing.
- Production build verification.
- Docker build verification.

Do not automatically deploy without explicit configuration and authorization.

# PHASE 17: DOCUMENTATION

Update the README with:

1. Project overview.
2. Main features.
3. Architecture.
4. Technology stack.
5. Prerequisites.
6. Local installation.
7. Environment configuration.
8. Running frontend and backend.
9. Running tests.
10. Docker deployment.
11. Vercel deployment.
12. Render deployment.
13. API documentation.
14. AI provider configuration.
15. Resume rewriting workflow.
16. PDF/DOCX export workflow.
17. Security considerations.

Create additional documentation where necessary.

---

# IMPLEMENTATION RULES

Follow these rules throughout the project:

1. Inspect before modifying.
2. Do not rewrite working functionality unnecessarily.
3. Preserve useful existing components.
4. Avoid unnecessary dependencies.
5. Do not introduce placeholder implementations and claim they are complete.
6. Do not silently remove existing features.
7. Do not hardcode API keys or credentials.
8. Do not expose server secrets to browser code.
9. Do not fabricate resume information.
10. Keep the application runnable after each major milestone.
11. Add tests for new functionality.
12. Keep code modular and maintainable.
13. Do not commit or push changes.
14. Do not deploy without explicit authorization.
15. Record significant architectural decisions.

When encountering a technical limitation, explain it and propose an appropriate solution instead of hiding it.

# REQUIRED EXECUTION STRATEGY

Execute this project in milestones.

**Milestone 1 — Repository audit**
- Inspect the entire repository.
- Identify architecture and technical debt.
- Produce audit and implementation documents.
- Report the findings.

**Milestone 2 — Architecture and refactoring**
- Refactor the application incrementally.
- Improve code organization.
- Centralize configuration.
- Improve error handling and security.
- Preserve existing functionality.

**Milestone 3 — Resume analysis**
- Improve document parsing.
- Implement structured extraction.
- Improve scoring and analysis.

**Milestone 4 — Job matching**
- Implement job description extraction.
- Implement job-specific matching.
- Add skill-gap analysis.

**Milestone 5 — AI resume rewriting**
- Implement the complete rewrite workflow.
- Preserve factual accuracy.
- Add section-level regeneration.
- Add before-and-after comparison.

**Milestone 6 — Document exports**
- Implement professional templates.
- Implement PDF and DOCX generation.
- Implement downloads and preview.

**Milestone 7 — Frontend improvements**
- Implement the complete user journey.
- Improve responsiveness and accessibility.

**Milestone 8 — Production deployment**
- Vercel.
- Render.
- Docker.
- Docker Compose.

**Milestone 9 — Testing and documentation**
- Run all automated tests.
- Verify production builds.
- Verify Docker.
- Complete deployment documentation.

Do not skip milestones or mark incomplete work as complete.

You may proceed through milestones autonomously once the audit is complete, but stop and report any architectural decision that requires significant user input.

# FINAL DELIVERY REPORT

At the end, provide a detailed report containing:

1. Original architecture.
2. New architecture.
3. Files created.
4. Files modified.
5. Files removed and why.
6. Features implemented.
7. AI resume rewriting workflow.
8. PDF/DOCX export implementation.
9. Security improvements.
10. Tests executed and results.
11. Production build results.
12. Docker build results.
13. Vercel deployment readiness.
14. Render deployment readiness.
15. Remaining environment configuration.
16. Known limitations.
17. Exact commands for running locally.
18. Exact commands for deploying.

Clearly distinguish between:

- Implemented and tested.
- Implemented but not tested.
- Requires external credentials.
- Requires manual deployment configuration.
- Not implemented.

The final objective is a genuinely production-ready AI Resume Analyzer, not merely a codebase that builds successfully.

Begin with Milestone 1: audit the existing repository and report your findings before making architectural changes.