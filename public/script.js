const chatLog = document.getElementById('chatLog')
const chatInput = document.getElementById('chatInput')
const downloadBtn = document.getElementById('downloadBtn')
const photoInput = document.getElementById('photoInput')
const pPhoto = document.getElementById('pPhoto')
const photoLabel = document.getElementById('photoLabel')
const previewBtn = document.getElementById('previewBtn')
const previewStatus = document.getElementById('previewStatus')
const paperEl = document.getElementById('paper')

let conversation = []
let resumeData = null
let currentTemplate = 'classic'

// TEMPLATE PICKER
document.querySelectorAll('.tpl-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tpl-btn').forEach(b => b.classList.remove('active'))
    btn.classList.add('active')
    currentTemplate = btn.dataset.template
    paperEl.className = `paper theme-${currentTemplate}`
  })
})

function setTemplate(template) {
  const btn = document.querySelector(`.tpl-btn[data-template="${template}"]`)
  if (btn) {
    document.querySelectorAll('.tpl-btn').forEach(b => b.classList.remove('active'))
    btn.classList.add('active')
  }
  currentTemplate = template
  paperEl.className = `paper theme-${template}`
}

// PHOTO UPLOAD
photoInput.addEventListener('change', (e) => {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    if (!resumeData) resumeData = {}
    resumeData.photo = reader.result
    pPhoto.src = reader.result
    pPhoto.style.display = 'block'
    photoLabel.style.display = 'none'
  }
  reader.readAsDataURL(file)
})

function addLine(role, text) {
  const div = document.createElement('div')
  div.className = `line ${role}`
  div.textContent = text
  chatLog.appendChild(div)
  chatLog.scrollTop = chatLog.scrollHeight
}

function showTyping() {
  const div = document.createElement('div')
  div.className = 'line typing'
  div.id = 'typingLine'
  div.textContent = 'thinking…'
  chatLog.appendChild(div)
  chatLog.scrollTop = chatLog.scrollHeight
}
function hideTyping() {
  document.getElementById('typingLine')?.remove()
}

function parseReply(raw) {
  const marker = '###RESUME_DATA###'
  const endMarker = '###END###'
  if (typeof raw !== 'string') {
    raw = String(raw)
  }

  const idx = raw.indexOf(marker)
  if (idx === -1) {
    return { text: raw.trim(), data: null }
  }

  const text = raw.slice(0, idx).trim()
  const endIdx = raw.indexOf(endMarker, idx + marker.length)
  let jsonPart = endIdx !== -1 ? raw.slice(idx + marker.length, endIdx) : raw.slice(idx + marker.length)
  jsonPart = jsonPart.replace(/[\u0000-\u001F\u007F-\u009F]/g, '').trim()

  try {
    return { text, data: JSON.parse(jsonPart) }
  } catch (e) {
    const fallbackStart = jsonPart.indexOf('{')
    const fallbackEnd = jsonPart.lastIndexOf('}')
    if (fallbackStart !== -1 && fallbackEnd > fallbackStart) {
      const fallback = jsonPart.slice(fallbackStart, fallbackEnd + 1)
      try {
        return { text, data: JSON.parse(fallback) }
      } catch (err) {
        console.error('[resume] fallback JSON parse failed', err)
      }
    }
    console.error('[resume] failed to parse resume JSON — likely truncated response', e, jsonPart)
    return { text: text + " (Note: I may have missed saving some of that — could you repeat it?)", data: null }
  }
}

function buildContactHTML(data) {
  const parts = []
  if (data.email) parts.push(`<a href="mailto:${data.email}">${data.email}</a>`)
  if (data.phone) parts.push(`<a href="tel:${data.phone.replace(/\s+/g, '')}">${data.phone}</a>`)
  if (data.linkedin) {
    const raw = data.linkedin.trim()
    const normalized = normalizeLinkedInHandle(raw)
    parts.push(`<a href="${normalized}" target="_blank" rel="noopener">LinkedIn</a>`)
  }
  if (data.github) {
    const raw = data.github.trim()
    const normalized = normalizeGitHubHandle(raw)
    parts.push(`<a href="${normalized}" target="_blank" rel="noopener">GitHub</a>`)
  }
  if (data.location) parts.push(data.location)
  return parts.join(' &middot; ') || 'email &middot; phone &middot; location &middot; LinkedIn &middot; GitHub'
}

function normalizeLinkedInHandle(value) {
  const cleaned = value.trim().replace(/^linkedin[:\s\/\\]*/i, '').replace(/^https?:\/\//i, '').replace(/^www\./i, '')
  if (cleaned.toLowerCase().startsWith('linkedin.com')) {
    return `https://${cleaned}`
  }
  return `https://linkedin.com/in/${cleaned}`
}

function normalizeGitHubHandle(value) {
  const cleaned = value.trim().replace(/^github[:\s\/\\]*/i, '').replace(/^https?:\/\//i, '').replace(/^www\./i, '')
  if (cleaned.toLowerCase().startsWith('github.com')) {
    return `https://${cleaned}`
  }
  return `https://github.com/${cleaned}`
}

function parseArrayField(value) {
  if (!value && value !== 0) return []
  if (Array.isArray(value)) {
    return value.flatMap(v => {
      if (typeof v === 'object' && v !== null) {
        return Object.values(v).map(String).join(', ').split(/[\n,]+/).map(item => item.trim()).filter(Boolean)
      }
      return String(v).split(/[\n,]+/).map(item => item.trim()).filter(Boolean)
    }).filter(Boolean)
  }
  if (typeof value === 'object' && value !== null) {
    return Object.values(value).map(String).join(', ').split(/[\n,]+/).map(item => item.trim()).filter(Boolean)
  }
  if (typeof value === 'string') {
    return value.split(/[\n,]+/).map(item => item.trim()).filter(Boolean)
  }
  return []
}

function mergeResumeData(existing = {}, incoming = {}) {
  const merged = { ...existing }
  const fields = ['name', 'email', 'phone', 'location', 'linkedin', 'github', 'summary']
  fields.forEach(field => {
    if (incoming[field] || (!merged[field] && incoming[field] === '')) {
      merged[field] = incoming[field]
    }
  })
  if (Array.isArray(incoming.experience) && incoming.experience.length) {
    merged.experience = incoming.experience
  } else if (!Array.isArray(merged.experience)) {
    merged.experience = []
  }
  if (Array.isArray(incoming.skills) && incoming.skills.length) {
    merged.skills = incoming.skills
  } else if (typeof incoming.skills === 'string' && incoming.skills.trim()) {
    merged.skills = parseArrayField(incoming.skills)
  } else if (!Array.isArray(merged.skills)) {
    merged.skills = []
  }
  if (Array.isArray(incoming.education) && incoming.education.length) {
    merged.education = incoming.education
  } else if (!Array.isArray(merged.education)) {
    merged.education = []
  }
  if (Array.isArray(incoming.certifications) && incoming.certifications.length) {
    merged.certifications = incoming.certifications
  } else if (typeof incoming.certifications === 'string' && incoming.certifications.trim()) {
    merged.certifications = parseArrayField(incoming.certifications)
  } else if (!Array.isArray(merged.certifications)) {
    merged.certifications = []
  }
  if (Array.isArray(incoming.projects) && incoming.projects.length) {
    merged.projects = incoming.projects
  } else if (typeof incoming.projects === 'string' && incoming.projects.trim()) {
    merged.projects = parseArrayField(incoming.projects)
  } else if (!Array.isArray(merged.projects)) {
    merged.projects = []
  }
  if (Array.isArray(incoming.additional_sections) && incoming.additional_sections.length) {
    merged.additional_sections = incoming.additional_sections
  } else if (!Array.isArray(merged.additional_sections)) {
    merged.additional_sections = []
  }
  return merged
}

function updatePaper(data) {
  if (!data) return
  const existingPhoto = resumeData?.photo
  resumeData = mergeResumeData(resumeData, data)
  if (existingPhoto) {
    resumeData.photo = existingPhoto
  }

  document.getElementById('pName').textContent = resumeData.name || 'Your Name'
  document.getElementById('pContact').innerHTML = buildContactHTML(resumeData)

  const summaryEl = document.getElementById('pSummary')
  summaryEl.textContent = resumeData.summary || 'Not yet provided'
  summaryEl.classList.toggle('empty', !resumeData.summary)

  const expEl = document.getElementById('pExperience')
  const hasExperience = resumeData.experience && resumeData.experience.length
  if (hasExperience) {
    expEl.classList.remove('empty')
    expEl.innerHTML = resumeData.experience.map((exp, i) => `
      <div class="exp-item">
        <div class="exp-title">${exp.title || ''} — ${exp.company || ''}</div>
        <div class="exp-meta">${exp.dates || ''}</div>
        <ul contenteditable="true" data-exp-index="${i}" class="editable-list">
          ${(exp.achievements || []).map(a => `<li>${a}</li>`).join('') || '<li>Click to add achievements…</li>'}
        </ul>
      </div>
    `).join('')

    expEl.querySelectorAll('.editable-list').forEach(ul => {
      ul.addEventListener('blur', () => {
        const idx = parseInt(ul.dataset.expIndex)
        const lines = Array.from(ul.querySelectorAll('li')).map(li => li.textContent.trim()).filter(Boolean)
        resumeData.experience[idx].achievements = lines
      })
    })
  } else {
    expEl.classList.add('empty')
    expEl.innerHTML = '<div class="placeholder">Not yet provided</div>'
  }

  const eduEl = document.getElementById('pEducation')
  const hasEducation = resumeData.education && resumeData.education.length
  if (hasEducation) {
    eduEl.classList.remove('empty')
    eduEl.innerHTML = resumeData.education.map(e => {
      const text = typeof e === 'object' ? Object.values(e).filter(Boolean).join(', ') : e
      return `<div>${text}</div>`
    }).join('')
  } else {
    eduEl.classList.add('empty')
    eduEl.innerHTML = '<div class="placeholder">Not yet provided</div>'
  }

  const skillsEl = document.getElementById('pSkills')
  const skills = parseArrayField(resumeData.skills)
  const hasSkills = skills.length
  skillsEl.textContent = hasSkills ? skills.join(', ') : 'Not yet provided'
  skillsEl.classList.toggle('empty', !hasSkills)

  const additionalSectionsEl = document.getElementById('pAdditionalSections')
  if (resumeData.additional_sections && resumeData.additional_sections.length) {
    const extraSections = resumeData.additional_sections.filter(section => {
      const title = (section.section || section.title || '').toString().toLowerCase()
      return !(title.includes('certif') || title.includes('training') || title.includes('project') || title.includes('achievement'))
    })

    if (extraSections.length) {
      additionalSectionsEl.innerHTML = extraSections.map(section => {
        const rawTitle = section.section || section.title || 'Additional'
        const title = normalizeSectionTitle(rawTitle)
        const content = section.items || section.content || []
        const items = Array.isArray(content) ? content : [content]
        const rendered = items.map(item => `<li>${typeof item === 'object' ? Object.values(item).filter(Boolean).join(', ') : item}</li>`).join('')
        return `
          <div class="paper-section">
            <h2>${title}</h2>
            <ul>${rendered}</ul>
          </div>
        `
      }).join('')
    } else {
      additionalSectionsEl.innerHTML = ''
    }
  } else {
    additionalSectionsEl.innerHTML = ''
  }

  // Certifications
  const certsEl = document.getElementById('pCerts')
  const certSection = (resumeData.additional_sections || []).find(s => {
    const t = (s.section || s.title || '').toString().toLowerCase()
    return t.includes('certif') || t.includes('training')
  })
  if (certSection && (certSection.items || certSection.content)) {
    const items = Array.isArray(certSection.items || certSection.content) ? (certSection.items || certSection.content) : [certSection.items || certSection.content]
    certsEl.classList.remove('empty')
    certsEl.innerHTML = items.map(i => `<li>${typeof i === 'object' ? Object.values(i).filter(Boolean).join(', ') : i}</li>`).join('')
  } else if (resumeData.certifications && resumeData.certifications.length) {
    certsEl.classList.remove('empty')
    certsEl.innerHTML = resumeData.certifications.map(c => `<li>${c}</li>`).join('')
  } else {
    certsEl.classList.add('empty')
    certsEl.innerHTML = '<li>Not yet provided</li>'
  }

  // Projects
  const projectsEl = document.getElementById('pProjects')
  const projSection = (resumeData.additional_sections || []).find(s => {
    const t = (s.section || s.title || '').toString().toLowerCase()
    return t.includes('project') || t.includes('achievement')
  })
  if (projSection && (projSection.items || projSection.content)) {
    const items = Array.isArray(projSection.items || projSection.content) ? (projSection.items || projSection.content) : [projSection.items || projSection.content]
    projectsEl.classList.remove('empty')
    projectsEl.innerHTML = items.map(i => `<li>${typeof i === 'object' ? Object.values(i).filter(Boolean).join(', ') : i}</li>`).join('')
  } else if (resumeData.projects && resumeData.projects.length) {
    projectsEl.classList.remove('empty')
    projectsEl.innerHTML = resumeData.projects.map(p => `<li>${p}</li>`).join('')
  } else {
    projectsEl.classList.add('empty')
    projectsEl.innerHTML = '<li>Not yet provided</li>'
  }

  if (existingPhoto) {
    pPhoto.src = existingPhoto
    pPhoto.style.display = 'block'
    photoLabel.style.display = 'none'
  } else {
    pPhoto.style.display = 'none'
    photoLabel.style.display = 'flex'
  }

  const hasAnyResumeContent = resumeData.name || resumeData.summary || (resumeData.experience && resumeData.experience.length) || (resumeData.education && resumeData.education.length) || (parseArrayField(resumeData.skills).length) || (parseArrayField(resumeData.certifications).length) || (parseArrayField(resumeData.projects).length) || (resumeData.additional_sections && resumeData.additional_sections.length) || resumeData.email || resumeData.phone || resumeData.location || resumeData.linkedin || resumeData.github || resumeData.photo
  downloadBtn.disabled = !hasAnyResumeContent
  previewBtn.disabled = !hasAnyResumeContent
  updateContactPreview()
}

function normalizeSectionTitle(title) {
  if (!title) return ''
  const t = String(title).trim().toLowerCase()
  if (t.includes('certif') || t.includes('training')) return 'CERTIFICATIONS & TRAINING'
  if (t.includes('project') || t.includes('achievement')) return 'KEY PROJECTS & ACHIEVEMENTS'
  return String(title).trim().toUpperCase()
}

function parseContactLine(text) {
  const parts = text.split(/\s*[·\|,]\s*/).map(p => p.trim()).filter(Boolean)
  const result = { email: '', phone: '', location: '', linkedin: '', github: '' }
  parts.forEach(part => {
    const lower = part.toLowerCase()
    if (!result.email && part.includes('@')) {
      result.email = part
      return
    }
    if (!result.phone && /^[+\d\s\-().]{7,}$/.test(part)) {
      result.phone = part
      return
    }
    if (!result.linkedin && (lower.includes('linkedin.com') || lower.startsWith('linkedin:') || lower.startsWith('linkedin'))) {
      if (lower === 'linkedin' || lower === 'linkedin.com') return
      result.linkedin = normalizeLinkedInHandle(part)
      return
    }
    if (!result.github && (lower.includes('github.com') || lower.startsWith('github:') || lower.startsWith('github'))) {
      if (lower === 'github' || lower === 'github.com') return
      result.github = normalizeGitHubHandle(part)
      return
    }
    if (!result.location) {
      result.location = part
    }
  })
  return result
}

function upsertAdditionalSection(title, items) {
  if (!resumeData) resumeData = {}
  if (!Array.isArray(resumeData.additional_sections)) resumeData.additional_sections = []
  const key = title.toLowerCase()
  const idx = resumeData.additional_sections.findIndex(s => {
    const t = (s.section || s.title || '').toString().toLowerCase()
    if (key.includes('certif')) return t.includes('certif') || t.includes('training')
    if (key.includes('project')) return t.includes('project') || t.includes('achievement')
    return t === key
  })
  const payload = { section: title, items: items }
  if (idx !== -1) resumeData.additional_sections[idx] = payload
  else resumeData.additional_sections.push(payload)
}

function updateContactPreview() {
  if (!resumeData) return
  document.getElementById('pContact').innerHTML = buildContactHTML(resumeData)
}

async function sendMessage(text) {
  addLine('user', text)
  conversation.push({ role: 'user', content: text })
  showTyping()

  try {
    const payload = { messages: conversation }

    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const raw = await res.json()
    hideTyping()

    if (!raw.reply) {
      addLine('bot', "Something went wrong on my end — try again?")
      return
    }

    const { text: botText, data } = parseReply(raw.reply)
    addLine('bot', botText)
    // Save only the assistant's visible text to conversation to avoid resending
    // the full raw reply (which contains appended JSON and can cause duplication).
    conversation.push({ role: 'assistant', content: botText })
    updatePaper(data)

  } catch (err) {
    console.error('[resume] request failed', err)
    hideTyping()
    addLine('bot', "Couldn't connect — please try again.")
  }
}

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && chatInput.value.trim()) {
    const text = chatInput.value.trim()
    chatInput.value = ''
    sendMessage(text)
  }
})

function makeEditable() {
  document.getElementById('pName').contentEditable = true
  document.getElementById('pContact').contentEditable = true
  document.getElementById('pSummary').contentEditable = true
  document.getElementById('pSkills').contentEditable = true

  document.getElementById('pName').addEventListener('blur', (e) => {
    if (!resumeData) resumeData = {}
    resumeData.name = e.target.textContent.trim()
    updatePaper(resumeData)
    previewStatus.textContent = 'Preview refreshed automatically.'
  })
  document.getElementById('pContact').addEventListener('blur', (e) => {
    if (!resumeData) resumeData = {}
    const parsed = parseContactLine(e.target.textContent)
    resumeData = { ...resumeData, ...parsed }
    updatePaper(resumeData)
    previewStatus.textContent = 'Preview refreshed automatically.'
  })
  // Certifications editable list
  const pCerts = document.getElementById('pCerts')
  if (pCerts) {
    pCerts.contentEditable = true
    pCerts.addEventListener('blur', (e) => {
      const lines = Array.from(pCerts.querySelectorAll('li')).map(li => li.textContent.trim()).filter(Boolean)
      if (lines.length) upsertAdditionalSection('CERTIFICATIONS & TRAINING', lines)
      else {
        // remove if empty
        if (resumeData && Array.isArray(resumeData.additional_sections)) {
          resumeData.additional_sections = resumeData.additional_sections.filter(s => { const t=(s.section||s.title||'').toLowerCase(); return !(t.includes('certif')||t.includes('training')) })
        }
      }
      updatePaper(resumeData)
      previewStatus.textContent = 'Preview refreshed automatically.'
    })
  }
  // Projects editable list
  const pProjects = document.getElementById('pProjects')
  if (pProjects) {
    pProjects.contentEditable = true
    pProjects.addEventListener('blur', (e) => {
      const lines = Array.from(pProjects.querySelectorAll('li')).map(li => li.textContent.trim()).filter(Boolean)
      if (lines.length) upsertAdditionalSection('KEY PROJECTS & ACHIEVEMENTS', lines)
      else {
        if (resumeData && Array.isArray(resumeData.additional_sections)) {
          resumeData.additional_sections = resumeData.additional_sections.filter(s => { const t=(s.section||s.title||'').toLowerCase(); return !(t.includes('project')||t.includes('achievement')) })
        }
      }
      updatePaper(resumeData)
      previewStatus.textContent = 'Preview refreshed automatically.'
    })
  }
  document.getElementById('pSummary').addEventListener('blur', (e) => {
    if (!resumeData) resumeData = {}
    resumeData.summary = e.target.textContent.trim()
    updatePaper(resumeData)
    previewStatus.textContent = 'Preview refreshed automatically.'
  })
  document.getElementById('pSkills').addEventListener('blur', (e) => {
    if (!resumeData) resumeData = {}
    resumeData.skills = e.target.textContent.split(',').map(s => s.trim()).filter(Boolean)
    updatePaper(resumeData)
    previewStatus.textContent = 'Preview refreshed automatically.'
  })
}
makeEditable()

previewBtn?.addEventListener('click', async () => {
  if (!resumeData) resumeData = {}
  updatePaper(resumeData)
  previewStatus.textContent = 'Loading PDF preview…'
  previewBtn.disabled = true

  try {
    const res = await fetch('/api/generate-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...resumeData, template: currentTemplate }),
    })

    if (!res.ok) {
      throw new Error('Preview generation failed')
    }

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
    previewStatus.textContent = 'PDF preview opened in a new tab.'
  } catch (err) {
    console.error('[resume] preview failed', err)
    previewStatus.textContent = 'Preview failed. Please try again or download the PDF.'
  } finally {
    previewBtn.disabled = false
  }
})

downloadBtn.addEventListener('click', async () => {
  if (!resumeData) return

  downloadBtn.textContent = 'Generating…'
  downloadBtn.disabled = true

  try {
    const res = await fetch('/api/generate-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...resumeData, template: currentTemplate }),
    })

    if (!res.ok) throw new Error('PDF generation failed')

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${(resumeData.name || 'resume').replace(/\s+/g, '_')}_Resume.pdf`
    a.click()
    URL.revokeObjectURL(url)

  } catch (err) {
    console.error('[resume] pdf download failed', err)
    alert('Something went wrong generating the PDF. Please try again.')
  } finally {
    downloadBtn.textContent = 'Download PDF'
    downloadBtn.disabled = false
  }
})