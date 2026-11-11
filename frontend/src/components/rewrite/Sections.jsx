import { useState } from 'react'
import SuggestionCard from './SuggestionCard'

const clone = (value) => JSON.parse(JSON.stringify(value))
const dates = (start, end) => [start, end].filter(Boolean).join(' – ')
const splitList = (text) =>
  text
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean)

let newId = 0
const userId = (prefix) => `${prefix}-u${Date.now().toString(36)}${(newId++).toString(36)}`

function Shell({ title, children, actions }) {
  return (
    <section className="rewrite-section" aria-label={title}>
      <header className="rewrite-section-head">
        <h2>{title}</h2>
        <div className="rewrite-section-actions">{actions}</div>
      </header>
      {children}
    </section>
  )
}

function SectionActions({ ctx, scope, label, onEdit, editing, extra }) {
  if (ctx.readOnly) return null
  return (
    <>
      {extra}
      {scope && (
        <button
          type="button"
          className="btn-small is-secondary"
          onClick={() => ctx.onRegenerate(scope)}
          disabled={ctx.busy}
        >
          Regenerate {label}
        </button>
      )}
      {onEdit && !editing && (
        <button type="button" className="btn-small is-secondary" onClick={onEdit} disabled={ctx.busy}>
          Edit
        </button>
      )}
    </>
  )
}

function Suggestions({ ctx, unit }) {
  const items = ctx.suggestions.filter((s) => s.unit === unit)
  if (!items.length) return null
  return (
    <div className="suggestion-list">
      {items.map((suggestion) => (
        <SuggestionCard
          key={suggestion.id}
          suggestion={suggestion}
          onDecide={ctx.onDecide}
          busy={ctx.busy}
          readOnly={ctx.readOnly}
        />
      ))}
    </div>
  )
}

function EditorButtons({ ctx, onSave, onCancel, note }) {
  return (
    <div className="editor-buttons">
      {note && <p className="report-meta">{note}</p>}
      <button type="button" className="btn-small" onClick={onSave} disabled={ctx.busy}>
        {ctx.busy ? 'Saving…' : 'Save changes'}
      </button>
      <button type="button" className="btn-small is-secondary" onClick={onCancel} disabled={ctx.busy}>
        Cancel
      </button>
    </div>
  )
}

function Field({ label, value, onChange, multiline = false, maxLength = 300 }) {
  return (
    <label className="field-label">
      {label}
      {multiline ? (
        <textarea
          className="jd-textarea"
          rows={3}
          value={value ?? ''}
          maxLength={maxLength}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          className="text-input"
          value={value ?? ''}
          maxLength={maxLength}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  )
}

/**
 * A comma-separated list. The raw text is kept while typing (re-splitting on every keystroke would swallow the
 * comma before the next item is typed); the parsed list is passed up on every change.
 */
function ListField({ label, values, onChange, maxLength = 4000 }) {
  const [raw, setRaw] = useState(() => (values || []).join(', '))
  return (
    <Field
      label={label}
      multiline
      maxLength={maxLength}
      value={raw}
      onChange={(v) => {
        setRaw(v)
        onChange(splitList(v))
      }}
    />
  )
}

/** Shared editing state for one section: a draft copy of the content, saved as a whole new version. */
function useDraft(ctx) {
  const [draft, setDraft] = useState(null)
  return {
    draft,
    editing: draft !== null,
    start: () => setDraft(clone(ctx.content)),
    cancel: () => setDraft(null),
    update: (fn) =>
      setDraft((current) => {
        const next = clone(current)
        fn(next)
        return next
      }),
    /** Saves the draft (optionally transformed first); resolves to true when the server accepted it. */
    save: async (transform) => {
      // Buttons call save(event); only a function is a transform.
      const payload = typeof transform === 'function' ? transform(clone(draft)) : draft
      const ok = await ctx.onSaveContent(payload)
      if (ok) setDraft(null)
      return ok
    },
  }
}

// --------------------------------------------------------------------------- sections

export function ContactSection({ ctx }) {
  const edit = useDraft(ctx)
  const contact = ctx.content.contact
  return (
    <Shell title="Contact details" actions={<SectionActions ctx={ctx} onEdit={edit.start} editing={edit.editing} />}>
      {!edit.editing ? (
        <p className="current-text">
          <strong>{contact.name || 'No name'}</strong>
          <br />
          {[contact.email, contact.phone, contact.location, ...contact.links.map((l) => l.url)]
            .filter(Boolean)
            .join(' · ')}
        </p>
      ) : (
        <div className="editor">
          <p className="report-meta">Contact details are never sent to the AI.</p>
          {['name', 'email', 'phone', 'location'].map((key) => (
            <Field
              key={key}
              label={key[0].toUpperCase() + key.slice(1)}
              value={edit.draft.contact[key]}
              onChange={(v) =>
                edit.update((d) => {
                  d.contact[key] = v || null
                })
              }
            />
          ))}
          <Field
            label="Links (one per line, https://…)"
            multiline
            maxLength={2000}
            value={edit.draft.contact.links.map((l) => l.url).join('\n')}
            onChange={(v) =>
              edit.update((d) => {
                d.contact.links = splitList(v).map((url) => ({
                  url,
                  kind: url.includes('linkedin.') ? 'linkedin' : url.includes('github.') ? 'github' : 'website',
                }))
              })
            }
          />
          <EditorButtons ctx={ctx} onSave={edit.save} onCancel={edit.cancel} />
        </div>
      )}
    </Shell>
  )
}

export function SummarySection({ ctx }) {
  const edit = useDraft(ctx)
  return (
    <Shell
      title="Professional summary"
      actions={<SectionActions ctx={ctx} scope="summary" label="summary" onEdit={edit.start} editing={edit.editing} />}
    >
      <Suggestions ctx={ctx} unit="summary" />
      {!edit.editing ? (
        <div className="current-block">
          <span className="compare-label">In your rewritten resume</span>
          <p className="current-text">{ctx.content.summary || <em className="field-missing">No summary</em>}</p>
        </div>
      ) : (
        <div className="editor">
          <Field
            label="Summary"
            multiline
            maxLength={2000}
            value={edit.draft.summary}
            onChange={(v) =>
              edit.update((d) => {
                d.summary = v || null
              })
            }
          />
          <EditorButtons ctx={ctx} onSave={edit.save} onCancel={edit.cancel} />
        </div>
      )}
    </Shell>
  )
}

function RoleEditor({ ctx, edit, index }) {
  const role = edit.draft.experience[index]
  const set = (key) => (value) =>
    edit.update((d) => {
      d.experience[index][key] = value || null
    })
  return (
    <div className="editor">
      <div className="editor-grid">
        <Field label="Job title" value={role.title} onChange={set('title')} />
        <Field label="Employer" value={role.employer} onChange={set('employer')} />
        <Field label="Start date" value={role.start_date} onChange={set('start_date')} maxLength={40} />
        <Field label="End date" value={role.end_date} onChange={set('end_date')} maxLength={40} />
      </div>
      <p className="report-meta">
        Changing titles, employers or dates is flagged, because they will no longer match your original resume.
      </p>
      {role.bullets.map((bullet, position) => (
        <div key={bullet.id} className="bullet-editor">
          <Field
            label={`Bullet ${position + 1}`}
            multiline
            maxLength={600}
            value={bullet.text}
            onChange={(v) =>
              edit.update((d) => {
                d.experience[index].bullets[position].text = v
              })
            }
          />
          <button
            type="button"
            className="btn-quiet"
            onClick={() =>
              edit.update((d) => {
                d.experience[index].bullets.splice(position, 1)
              })
            }
          >
            Remove bullet
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn-quiet"
        onClick={() =>
          edit.update((d) => {
            d.experience[index].bullets.push({ id: userId('b'), text: '', source_ids: [] })
          })
        }
      >
        + Add bullet
      </button>
      <EditorButtons
        ctx={ctx}
        onSave={() =>
          edit.save((d) => {
            d.experience[index].bullets = d.experience[index].bullets.filter((b) => b.text.trim())
            return d
          })
        }
        onCancel={edit.cancel}
        note="Accepting or rejecting a suggestion in this role later rebuilds its bullets from the suggestions and discards these manual edits."
      />
    </div>
  )
}

export function ExperienceSection({ ctx, selected, onToggle }) {
  const edit = useDraft(ctx)
  const [editingRole, setEditingRole] = useState(null)
  if (!ctx.content.experience.length) return null
  return (
    <Shell
      title="Experience"
      actions={
        <SectionActions
          ctx={ctx}
          scope="experience"
          label="all bullets"
          extra={
            selected.length > 0 && (
              <button
                type="button"
                className="btn-small"
                onClick={() => ctx.onRegenerate('bullets', selected)}
                disabled={ctx.busy}
              >
                Regenerate {selected.length} selected
              </button>
            )
          }
        />
      }
    >
      {ctx.content.experience.map((role, index) => (
        <div key={role.id} className="role-block">
          <div className="role-head">
            <div>
              <strong>{role.title || 'Untitled role'}</strong>
              {role.employer ? `, ${role.employer}` : ''}
              <span className="report-meta"> {dates(role.start_date, role.end_date)}</span>
            </div>
            {!ctx.readOnly && editingRole !== index && (
              <button
                type="button"
                className="btn-small is-secondary"
                onClick={() => {
                  edit.start()
                  setEditingRole(index)
                }}
                disabled={ctx.busy || edit.editing}
              >
                Edit role
              </button>
            )}
          </div>
          <Suggestions ctx={ctx} unit={`experience:${role.id}`} />
          {edit.editing && editingRole === index ? (
            <RoleEditor
              ctx={ctx}
              index={index}
              edit={{
                ...edit,
                cancel: () => {
                  edit.cancel()
                  setEditingRole(null)
                },
                save: async (transform) => {
                  const ok = await edit.save(transform)
                  if (ok) setEditingRole(null)
                  return ok
                },
              }}
            />
          ) : (
            <div className="current-block">
              <span className="compare-label">
                In your rewritten resume{!ctx.readOnly && ' (tick bullets to regenerate them)'}
              </span>
              <ul className="bullet-list">
                {role.bullets.map((bullet) => (
                  <li key={bullet.id}>
                    {!ctx.readOnly && (
                      <input
                        type="checkbox"
                        aria-label={`Select bullet for regeneration: ${bullet.text}`}
                        checked={selected.includes(bullet.id)}
                        onChange={() => onToggle(bullet.id)}
                        disabled={!bullet.source_ids.length}
                      />
                    )}
                    <span>{bullet.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}
    </Shell>
  )
}

export function SkillsSection({ ctx }) {
  const edit = useDraft(ctx)
  const { technical_skills: technical, soft_skills: soft } = ctx.content
  if (!technical.length && !soft.length && !ctx.suggestions.some((s) => s.unit === 'skills')) return null
  return (
    <Shell
      title="Skills"
      actions={
        <SectionActions ctx={ctx} scope="skills" label="skills order" onEdit={edit.start} editing={edit.editing} />
      }
    >
      <Suggestions ctx={ctx} unit="skills" />
      {!edit.editing ? (
        <div className="current-block">
          <span className="compare-label">In your rewritten resume</span>
          <p className="current-text">
            <strong>Technical:</strong> {technical.join(', ') || '—'}
            <br />
            <strong>Professional:</strong> {soft.join(', ') || '—'}
          </p>
        </div>
      ) : (
        <div className="editor">
          <ListField
            label="Technical skills (comma-separated)"
            values={edit.draft.technical_skills}
            onChange={(list) =>
              edit.update((d) => {
                d.technical_skills = list
              })
            }
          />
          <ListField
            label="Professional skills (comma-separated)"
            maxLength={2000}
            values={edit.draft.soft_skills}
            onChange={(list) =>
              edit.update((d) => {
                d.soft_skills = list
              })
            }
          />
          <EditorButtons
            ctx={ctx}
            onSave={edit.save}
            onCancel={edit.cancel}
            note="Skills that your original resume doesn't mention are flagged as unsupported."
          />
        </div>
      )}
    </Shell>
  )
}

export function ProjectsSection({ ctx }) {
  const edit = useDraft(ctx)
  if (!ctx.content.projects.length) return null
  return (
    <Shell
      title="Projects"
      actions={
        <SectionActions ctx={ctx} scope="projects" label="projects" onEdit={edit.start} editing={edit.editing} />
      }
    >
      {ctx.content.projects.map((project, index) => (
        <div key={project.id} className="role-block">
          <div className="role-head">
            <strong>{project.name || 'Project'}</strong>
          </div>
          <Suggestions ctx={ctx} unit={`project:${project.id}`} />
          {edit.editing ? (
            <Field
              label="Description"
              multiline
              maxLength={2000}
              value={edit.draft.projects[index].description}
              onChange={(v) =>
                edit.update((d) => {
                  d.projects[index].description = v || null
                })
              }
            />
          ) : (
            <p className="current-text">{project.description}</p>
          )}
        </div>
      ))}
      {edit.editing && <EditorButtons ctx={ctx} onSave={edit.save} onCancel={edit.cancel} />}
    </Shell>
  )
}

export function EducationSection({ ctx }) {
  const edit = useDraft(ctx)
  const { education, certifications } = ctx.content
  if (!education.length && !certifications.length) return null
  return (
    <Shell
      title="Education and certifications"
      actions={<SectionActions ctx={ctx} scope="education" label="order" onEdit={edit.start} editing={edit.editing} />}
    >
      <Suggestions ctx={ctx} unit="education" />
      <Suggestions ctx={ctx} unit="certifications" />
      {!edit.editing ? (
        <ul className="bullet-list">
          {education.map((e) => (
            <li key={e.id}>
              <span>
                {[e.qualification, e.field_of_study].filter(Boolean).join(' ')}
                {e.institution ? `, ${e.institution}` : ''}{' '}
                <span className="report-meta">{dates(e.start_date, e.end_date)}</span>
                {e.coursework?.length > 0 && (
                  <>
                    <br />
                    <small>Relevant coursework: {e.coursework.join(', ')}</small>
                  </>
                )}
              </span>
            </li>
          ))}
          {certifications.map((c) => (
            <li key={c.id}>
              <span>{[c.name, c.issuer, c.date].filter(Boolean).join(', ')}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="editor">
          {edit.draft.education.map((e, index) => (
            <div key={e.id} className="editor-grid">
              {['qualification', 'field_of_study', 'institution', 'end_date'].map((key) => (
                <Field
                  key={key}
                  label={key.replace(/_/g, ' ')}
                  value={e[key]}
                  maxLength={key === 'end_date' ? 40 : 300}
                  onChange={(v) =>
                    edit.update((d) => {
                      d.education[index][key] = v || null
                    })
                  }
                />
              ))}
              <ListField
                label="Relevant coursework (comma-separated)"
                maxLength={3000}
                values={e.coursework}
                onChange={(list) =>
                  edit.update((d) => {
                    d.education[index].coursework = list
                  })
                }
              />
            </div>
          ))}
          {edit.draft.certifications.map((c, index) => (
            <div key={c.id} className="editor-grid">
              {['name', 'issuer', 'date'].map((key) => (
                <Field
                  key={key}
                  label={`Certification ${key}`}
                  value={c[key]}
                  maxLength={key === 'date' ? 40 : 300}
                  onChange={(v) =>
                    edit.update((d) => {
                      d.certifications[index][key] = v || null
                    })
                  }
                />
              ))}
            </div>
          ))}
          <EditorButtons
            ctx={ctx}
            onSave={edit.save}
            onCancel={edit.cancel}
            note="These are facts; changes are flagged because they no longer match your original resume. Courses your original resume doesn't mention are flagged as unverified."
          />
        </div>
      )}
    </Shell>
  )
}
