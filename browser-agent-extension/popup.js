// AG2 Browser Agent - Popup Script

// Legacy single-profile keys (kept for one-time migration)
const PERSONAL_PROFILE_KEY = 'fillninjaPersonalProfile';
const MATERIALS_KEY = 'fillninjaSavedMaterials';

// New multi-profile/multi-project storage keys
const PROFILES_KEY = 'fillninjaProfiles';
const ACTIVE_PROFILE_ID_KEY = 'fillninjaActiveProfileId';
const PROJECTS_KEY = 'fillninjaProjects';
const ACTIVE_PROJECT_ID_KEY = 'fillninjaActiveProjectId';

function genId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

class PopupController {
    constructor() {
        this.taskInput = document.getElementById('taskInput');
        this.runBtn = document.getElementById('runBtn');
        this.stopBtn = document.getElementById('stopBtn');
        this.statusDot = document.getElementById('statusDot');
        this.statusText = document.getElementById('statusText');
        this.quickActionBtns = document.querySelectorAll('.quick-action-btn');
        this.discoverFormsBtn = document.getElementById('discoverFormsBtn');
        this.fillFromLastDiscoveryBtn = document.getElementById('fillFromLastDiscoveryBtn');
        this.maxFormsInput = document.getElementById('maxFormsInput');
        this.maxParallelInput = document.getElementById('maxParallelInput');
        this.projectFileInput = document.getElementById('projectFileInput');
        this.clearFileBtn = document.getElementById('clearFileBtn');
        this.sourceUrlInput = document.getElementById('sourceUrlInput');
        this.pickProjectFileBtn = document.getElementById('pickProjectFileBtn');
        this.unfilledReminderBtn = document.getElementById('unfilledReminderBtn');
        this.navMainTab = document.getElementById('navMainTab');
        this.navProfileTab = document.getElementById('navProfileTab');
        this.pageMain = document.getElementById('page-main');
        this.pageProfile = document.getElementById('page-profile');

        // Context picker (main tab)
        this.projectSelect = document.getElementById('projectSelect');

        // Resume/Profile tab elements
        this.projectSelectTab = document.getElementById('projectSelectTab');
        this.projectNameInput = document.getElementById('projectNameInput');
        this.projectUrlInput = document.getElementById('projectUrlInput');
        this.projectContextInput = document.getElementById('projectContextInput');
        this.saveProjectTabBtn = document.getElementById('saveProjectTabBtn');
        this.projectTabSaveStatus = document.getElementById('projectTabSaveStatus');
        this.addProjectBtn = document.getElementById('addProjectBtn');
        this.deleteProjectBtn = document.getElementById('deleteProjectBtn');

        // Data
        this.projects = [];
        this.activeProjectId = '';

        this.isRunning = false;
        this.pipelineTotal = 0;
        this.pipelineDone = 0;

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.checkConnectionStatus();

        this.setupPageNav();
        void this.loadProfilesAndProjects();

        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') {
                return;
            }
            if (!this.isRunning || this.stopBtn.disabled) {
                return;
            }
            e.preventDefault();
            this.stopAgent();
        });

        // Check status periodically
        setInterval(() => this.checkConnectionStatus(), 5000);
    }

    setupEventListeners() {
        // Run button
        this.runBtn.addEventListener('click', () => this.runAgent());

        // Stop button
        this.stopBtn.addEventListener('click', () => this.stopAgent());


        // Context picker (main tab)
        if (this.projectSelect) {
            this.projectSelect.addEventListener('change', (e) => this.onProjectSelect(e.target.value));
        }

        // Resume/Profile tab controls
        if (this.projectSelectTab) {
            this.projectSelectTab.addEventListener('change', (e) => this.onProjectSelectTabChange(e.target.value));
        }
        if (this.addProjectBtn) {
            this.addProjectBtn.addEventListener('click', () => this.addProject());
        }
        if (this.deleteProjectBtn) {
            this.deleteProjectBtn.addEventListener('click', () => this.deleteProject());
        }
        if (this.saveProjectTabBtn) {
            this.saveProjectTabBtn.addEventListener('click', () => this.saveActiveProject());
        }

        if (this.unfilledReminderBtn) {
            this.unfilledReminderBtn.addEventListener('click', () => this.checkUnfilledThisTab());
        }

        // Quick action buttons
        this.quickActionBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt;
                this.taskInput.value = prompt;
                this.runAgent();
            });
        });

        if (this.discoverFormsBtn) {
            this.discoverFormsBtn.addEventListener('click', () => this.runDiscoverForms());
        }
        if (this.fillFromLastDiscoveryBtn) {
            this.fillFromLastDiscoveryBtn.addEventListener('click', () => this.runFillFromLastDiscovery());
        }

        if (this.pickProjectFileBtn && this.projectFileInput) {
            this.pickProjectFileBtn.addEventListener('click', () => this.projectFileInput.click());
        }

        if (this.clearFileBtn) {
            this.clearFileBtn.addEventListener('click', async () => {
                if (this.projectFileInput) this.projectFileInput.value = '';
                if (this.sourceUrlInput) this.sourceUrlInput.value = '';
                // Clear URL from active project
                const project = this.projects.find(p => p.id === this.activeProjectId);
                if (project) {
                    project.sourceUrl = '';
                    await chrome.storage.local.set({ [PROJECTS_KEY]: this.projects });
                    // Sync profile tab too
                    if (this.projectUrlInput) this.projectUrlInput.value = '';
                }
                try {
                    await chrome.storage.local.remove('fillninjaLastUploadExtract');
                } catch (e) {
                    /* ignore */
                }
                this.addLog('Cleared file and project link.', 'system');
            });
        }

        if (this.projectFileInput) {
            this.projectFileInput.addEventListener('change', () => {
                void this.onProjectFileSelected();
            });
        }

        // Sync URL input to active project
        if (this.sourceUrlInput) {
            this.sourceUrlInput.addEventListener('blur', () => {
                void this.saveUrlToActiveProject();
            });
        }

        // Listen for messages from background script
        chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
            this.handleMessage(message);
            sendResponse({ received: true });
        });
    }

    async onProjectFileSelected() {
        const input = this.projectFileInput;
        if (!input || !input.files || !input.files[0]) {
            return;
        }
        const f = input.files[0];
        const VIDEO_EXT = ['.mp4', '.webm', '.mov', '.mkv', '.mpeg', '.mpg', '.m4v', '.avi'];
        const lower = f.name.toLowerCase();
        const isVideo = VIDEO_EXT.some((e) => lower.endsWith(e));
        const kb = f.size / 1024;
        const sizeBit = kb >= 1024 ? `${(kb / 1024).toFixed(2)} MB` : `${kb.toFixed(1)} KB`;

        if (isVideo) {
            this.addLog(
                `Ready: "${f.name}" (${sizeBit}, video). Auto-extract runs for PDF, DOCX, or PPTX — use Discover forms for video.`,
                'system',
            );
            return;
        }
        if (!lower.endsWith('.pdf') && !lower.endsWith('.docx') && !lower.endsWith('.pptx')) {
            this.addLog(
                `Ready: "${f.name}" (${sizeBit}). Auto-extract supports PDF, DOCX, and PPTX — use Discover for other types.`,
                'system',
            );
            return;
        }
        if (f.size > 6 * 1024 * 1024) {
            this.addLog('File is larger than 6 MB; auto-extract skipped.', 'error');
            return;
        }

        this.addLog(`Profiling "${f.name}" on the server…`, 'system');
        try {
            const status = await chrome.runtime.sendMessage({ type: 'CHECK_STATUS' });
            if (!status || !status.connected) {
                throw new Error('Backend not connected — start the FillNinja server (uvicorn).');
            }
            const buf = await f.arrayBuffer();
            const documentBase64 = this.arrayBufferToBase64(buf);
            const applicantContext = await this.getApplicantContextForRun();
            const response = await chrome.runtime.sendMessage({
                type: 'PROFILE_DOCUMENT',
                documentBase64,
                documentName: f.name,
                applicantContext: applicantContext || undefined,
            });
            if (!response || !response.success) {
                throw new Error(response?.error || 'Profiling failed');
            }
            // Save the extracted context to the active resume
            if (response.applicantContext) {
                await this.saveDocumentExtractToActiveProject(response.applicantContext, f.name);
            }
            const resume = this.projects.find(p => p.id === this.activeProjectId);
            if (resume) {
                this.addLog(
                    `✓ Extracted "${f.name}" → saved to résumé "${resume.name}".`,
                    'system',
                );
            } else {
                this.addLog(
                    `✓ Extracted "${f.name}". Select a résumé on Profile tab to save it.`,
                    'system',
                );
            }
        } catch (e) {
            this.addLog(`Auto-profile error: ${e.message}`, 'error');
        }
    }

    async saveDocumentExtractToActiveProject(applicantContext, fileName = '') {
        const project = this.projects.find(p => p.id === this.activeProjectId);
        if (!project) {
            // If no active project, create one with auto-numbered name
            const id = genId();
            const existingNumbers = this.projects
                .map(p => {
                    const match = p.name.match(/^Resume(\d+)$/);
                    return match ? parseInt(match[1], 10) : 0;
                })
                .filter(n => n > 0);
            const nextNum = Math.max(...existingNumbers, 0) + 1;
            const projName = `Resume${nextNum}`;

            const newProj = {
                id,
                name: projName,
                sourceUrl: '',
                applicantContext,
                savedAt: new Date().toISOString()
            };
            this.projects.push(newProj);
            this.activeProjectId = id;
        } else {
            // Update the active project's context
            project.applicantContext = applicantContext;
            project.savedAt = new Date().toISOString();
        }
        await chrome.storage.local.set({ [PROJECTS_KEY]: this.projects, [ACTIVE_PROJECT_ID_KEY]: this.activeProjectId });
        this.populateProjectDropdowns();
        this.loadProjectTab();
    }

    async saveUrlToActiveProject() {
        const url = this.sourceUrlInput?.value?.trim() || '';
        const project = this.projects.find(p => p.id === this.activeProjectId);
        if (!project) return;

        project.sourceUrl = url;
        try {
            await chrome.storage.local.set({ [PROJECTS_KEY]: this.projects });
            this.loadProjectTab();
        } catch (e) {
            console.warn('Failed to save URL to project', e);
        }
    }

    setupPageNav() {
        if (!this.navMainTab || !this.navProfileTab || !this.pageMain || !this.pageProfile) {
            return;
        }
        this.navMainTab.addEventListener('click', () => this.setPopupPage('main'));
        this.navProfileTab.addEventListener('click', () => this.setPopupPage('profile'));
    }

    setPopupPage(page) {
        if (!this.navMainTab || !this.navProfileTab || !this.pageMain || !this.pageProfile) {
            return;
        }
        const isMain = page === 'main';
        this.pageMain.classList.toggle('hidden', !isMain);
        this.pageProfile.classList.toggle('hidden', isMain);
        this.navMainTab.classList.toggle('nav-tab-active', isMain);
        this.navProfileTab.classList.toggle('nav-tab-active', !isMain);
        this.navMainTab.setAttribute('aria-selected', isMain ? 'true' : 'false');
        this.navProfileTab.setAttribute('aria-selected', !isMain ? 'true' : 'false');

        if (!isMain) {
            // Switching to profile tab: sync UI
            this.loadProjectTab();
        }
    }

    async loadProfilesAndProjects() {
        try {
            const res = await chrome.storage.local.get([PROJECTS_KEY, ACTIVE_PROJECT_ID_KEY, PERSONAL_PROFILE_KEY, MATERIALS_KEY, 'fillninjaLastUploadExtract']);

            // Load or migrate projects/resumes
            this.projects = Array.isArray(res[PROJECTS_KEY]) ? res[PROJECTS_KEY] : [];
            if (this.projects.length === 0) {
                // Migrate old personal profile if it exists
                let migratedContent = '';
                if (res[PERSONAL_PROFILE_KEY]) {
                    migratedContent = String(res[PERSONAL_PROFILE_KEY]).trim();
                }
                // If no personal profile, check legacy materials
                if (!migratedContent && Array.isArray(res[MATERIALS_KEY])) {
                    for (const entry of res[MATERIALS_KEY]) {
                        if (!entry) continue;
                        const facts = entry.applicantFactsForForms ? String(entry.applicantFactsForForms).trim() : '';
                        if (facts) {
                            migratedContent = facts;
                            break;
                        }
                    }
                    if (!migratedContent) {
                        for (const entry of res[MATERIALS_KEY]) {
                            if (!entry) continue;
                            const s = entry.profileSummary ? String(entry.profileSummary).trim() : '';
                            if (s) {
                                migratedContent = s;
                                break;
                            }
                        }
                    }
                }
                // Check for last upload
                const uploadRec = res['fillninjaLastUploadExtract'];
                let migratedUpload = '';
                if (uploadRec && uploadRec.applicantContext) {
                    migratedUpload = String(uploadRec.applicantContext).trim();
                }

                // Create default resume entries from migrations
                if (migratedContent || migratedUpload) {
                    const resumeId = genId();
                    this.projects.push({
                        id: resumeId,
                        name: 'Resume1',
                        sourceUrl: '',
                        applicantContext: (migratedContent && migratedUpload) ? `${migratedContent}\n\n---\n\n${migratedUpload}` : (migratedContent || migratedUpload),
                        savedAt: new Date().toISOString()
                    });
                    this.activeProjectId = resumeId;
                } else {
                    // Create empty default
                    const resumeId = genId();
                    this.projects.push({
                        id: resumeId,
                        name: 'Resume1',
                        sourceUrl: '',
                        applicantContext: '',
                        savedAt: new Date().toISOString()
                    });
                    this.activeProjectId = resumeId;
                }
                await chrome.storage.local.set({ [PROJECTS_KEY]: this.projects, [ACTIVE_PROJECT_ID_KEY]: this.activeProjectId });
            } else {
                this.activeProjectId = res[ACTIVE_PROJECT_ID_KEY] || (this.projects.length > 0 ? this.projects[0].id : '');
            }

            this.populateProjectDropdowns();
            this.loadProjectTab();
        } catch (e) {
            console.warn('FillNinja loadProfilesAndProjects', e);
        }
    }

    populateProjectDropdowns() {
        if (this.projectSelect) {
            this.projectSelect.innerHTML = '';
            for (const p of this.projects) {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = p.name;
                opt.selected = p.id === this.activeProjectId;
                this.projectSelect.appendChild(opt);
            }
        }
        if (this.projectSelectTab) {
            this.projectSelectTab.innerHTML = '';
            for (const p of this.projects) {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = p.name;
                opt.selected = p.id === this.activeProjectId;
                this.projectSelectTab.appendChild(opt);
            }
        }
    }

    loadProjectTab() {
        const project = this.projects.find(p => p.id === this.activeProjectId);
        if (project) {
            if (this.projectNameInput) this.projectNameInput.value = project.name;
            if (this.projectUrlInput) this.projectUrlInput.value = project.sourceUrl || '';
            if (this.projectContextInput) this.projectContextInput.value = project.applicantContext || '';
            // Also sync the Agent tab's URL field to the active project
            if (this.sourceUrlInput) {
                this.sourceUrlInput.value = project.sourceUrl || '';
            }
        } else {
            // No project selected
            if (this.projectNameInput) this.projectNameInput.value = '';
            if (this.projectUrlInput) this.projectUrlInput.value = '';
            if (this.projectContextInput) this.projectContextInput.value = '';
            if (this.sourceUrlInput) {
                this.sourceUrlInput.value = '';
            }
        }
    }


    async saveActiveProject() {
        const project = this.projects.find(p => p.id === this.activeProjectId);
        if (!project) return;

        const name = this.projectNameInput?.value?.trim();
        if (!name) {
            if (this.projectTabSaveStatus) {
                this.projectTabSaveStatus.textContent = 'Project name cannot be empty.';
            }
            return;
        }

        project.name = name;
        project.sourceUrl = this.projectUrlInput?.value?.trim() || '';
        project.applicantContext = this.projectContextInput?.value || '';

        try {
            await chrome.storage.local.set({ [PROJECTS_KEY]: this.projects });
            this.populateProjectDropdowns();
            if (this.projectTabSaveStatus) {
                this.projectTabSaveStatus.textContent = 'Saved.';
                setTimeout(() => {
                    if (this.projectTabSaveStatus) {
                        this.projectTabSaveStatus.textContent = '';
                    }
                }, 2000);
            }
        } catch (e) {
            if (this.projectTabSaveStatus) {
                this.projectTabSaveStatus.textContent = 'Could not save.';
            }
        }
    }


    async addProject() {
        const id = genId();
        // Generate name like Resume2, Resume3, etc.
        const existingNumbers = this.projects
            .map(p => {
                const match = p.name.match(/^Resume(\d+)$/);
                return match ? parseInt(match[1], 10) : 0;
            })
            .filter(n => n > 0);
        const nextNum = Math.max(...existingNumbers, 0) + 1;
        const name = `Resume${nextNum}`;

        this.projects.push({ id, name, sourceUrl: '', applicantContext: '', savedAt: new Date().toISOString() });
        this.activeProjectId = id;
        await chrome.storage.local.set({ [PROJECTS_KEY]: this.projects, [ACTIVE_PROJECT_ID_KEY]: this.activeProjectId });
        this.populateProjectDropdowns();
        this.loadProjectTab();
    }

    async deleteProject() {
        const project = this.projects.find(p => p.id === this.activeProjectId);
        if (!project || !confirm(`Delete project "${project.name}"? This cannot be undone.`)) {
            return;
        }
        this.projects = this.projects.filter(p => p.id !== this.activeProjectId);
        this.activeProjectId = '';
        await chrome.storage.local.set({ [PROJECTS_KEY]: this.projects, [ACTIVE_PROJECT_ID_KEY]: this.activeProjectId });
        this.populateProjectDropdowns();
        this.loadProjectTab();
        this.addLog(`Deleted project "${project.name}".`, 'system');
    }

    async onProfileSelect(id) {
        this.activeProfileId = id;
        await chrome.storage.local.set({ [ACTIVE_PROFILE_ID_KEY]: id });
        this.populateProfileDropdowns();
    }

    async onProjectSelect(id) {
        this.activeProjectId = id;
        await chrome.storage.local.set({ [ACTIVE_PROJECT_ID_KEY]: id });
        this.populateProjectDropdowns();
        // Sync URL to the Agent tab when switching projects
        const project = this.projects.find(p => p.id === id);
        if (this.sourceUrlInput && project) {
            this.sourceUrlInput.value = project.sourceUrl || '';
        }
    }

    async onProfileSelectTabChange(id) {
        this.activeProfileId = id;
        await chrome.storage.local.set({ [ACTIVE_PROFILE_ID_KEY]: id });
        this.populateProfileDropdowns();
        this.loadProfileTab();
    }

    async onProjectSelectTabChange(id) {
        this.activeProjectId = id;
        await chrome.storage.local.set({ [ACTIVE_PROJECT_ID_KEY]: id });
        this.populateProjectDropdowns();
        this.loadProjectTab();
    }

    async checkConnectionStatus() {
        try {
            const response = await chrome.runtime.sendMessage({ type: 'CHECK_STATUS' });
            if (response && response.connected) {
                this.setConnected(true, response.prepareApplicantContextAvailable !== false);
            } else {
                this.setConnected(false);
            }
        } catch (error) {
            this.setConnected(false);
        }
    }

    setConnected(connected, prepareApplicantContextAvailable = true) {
        if (connected) {
            this.statusDot.classList.add('connected');
            if (prepareApplicantContextAvailable === false) {
                this.statusText.textContent =
                    'Backend reachable but outdated — stop port 8000, then from FillNinja: python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000';
            } else {
                this.statusText.textContent = 'Connected to FillNinja backend';
            }
        } else {
            this.statusDot.classList.remove('connected');
            this.statusText.textContent = 'Disconnected — start the Python server';
        }
    }

    async getApplicantContextForRun() {
        try {
            const maxChars = 12000;

            // Get active resume/profile context
            const resume = this.projects.find(p => p.id === this.activeProjectId);
            if (!resume || !resume.applicantContext) {
                return '';
            }

            const context = resume.applicantContext.trim();
            return context.length > maxChars ? context.slice(0, maxChars) : context;
        } catch (e) {
            console.warn('FillNinja getApplicantContextForRun', e);
        }
        return '';
    }

    async readProjectFileForAgentRun() {
        const file = this.projectFileInput && this.projectFileInput.files && this.projectFileInput.files[0];
        if (!file) {
            return null;
        }
        const lower = file.name.toLowerCase();
        if (file.size > 6 * 1024 * 1024) {
            throw new Error('Attached document must be 6 MB or smaller for Run on this tab.');
        }
        if (
            !lower.endsWith('.pdf') &&
            !lower.endsWith('.docx') &&
            !lower.endsWith('.pptx')
        ) {
            throw new Error(
                'For Run on this tab, attach a PDF, DOCX, or PPTX below. (Use Discover forms for video uploads.)',
            );
        }
        const buf = await file.arrayBuffer();
        return {
            documentBase64: this.arrayBufferToBase64(buf),
            documentName: file.name,
        };
    }

    async runAgent() {
        const task = this.taskInput.value.trim();
        if (!task) {
            this.addLog('Please enter a task', 'error');
            return;
        }

        this.isRunning = true;
        this.updateUIState();
        this.addLog(`Starting task: ${task}`, 'user');

        const applicantContext = await this.getApplicantContextForRun();
        const resume = this.projects.find(p => p.id === this.activeProjectId);
        const resumeName = resume?.name || 'untitled';
        if (applicantContext) {
            this.addLog(
                `Using résumé/profile "${resumeName}".`,
                'system'
            );
        } else {
            this.addLog(
                '⚠️ No résumé/profile selected or empty. Go to Profile tab to upload a résumé or fill in facts.',
                'system'
            );
        }

        let docPayload = null;
        try {
            docPayload = await this.readProjectFileForAgentRun();
        } catch (err) {
            this.addLog(`Error: ${err.message}`, 'error');
            this.isRunning = false;
            this.updateUIState();
            return;
        }
        if (docPayload) {
            this.addLog(
                `Attached ${docPayload.documentName}: the server profiles it first, then the extension reads the active tab — use an https:// page with the form (not chrome:// or the extensions page).`,
                'system'
            );
        } else if (!applicantContext) {
            this.addLog(
                'No My profile text and no cached résumé — attach a PDF/DOCX/PPTX or fill in My profile.',
                'system'
            );
        }

        try {
            // Get current tab info
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

            const response = await chrome.runtime.sendMessage({
                type: 'RUN_AGENT',
                task: task,
                tabId: tab.id,
                url: tab.url,
                title: tab.title,
                applicantContext: applicantContext || undefined,
                documentBase64: docPayload ? docPayload.documentBase64 : undefined,
                documentName: docPayload ? docPayload.documentName : undefined,
            });

            if (!response || !response.success) {
                throw new Error(response?.error || 'Failed to start agent');
            }

            this.addLog('Agent started on this tab', 'system');
        } catch (error) {
            this.addLog(`Error: ${error.message}`, 'error');
            this.isRunning = false;
            this.updateUIState();
        }
    }

    normalizeSourceUrl(raw) {
        const t = (raw || '').trim();
        if (!t) return '';
        if (/^https?:\/\//i.test(t)) return t;
        return `https://${t}`;
    }

    arrayBufferToBase64(buffer) {
        let binary = '';
        const bytes = new Uint8Array(buffer);
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
            const slice = bytes.subarray(i, i + chunk);
            binary += String.fromCharCode.apply(null, slice);
        }
        return btoa(binary);
    }

    async runDiscoverForms() {
        const objective = this.taskInput.value.trim();
        const file = this.projectFileInput && this.projectFileInput.files && this.projectFileInput.files[0];

        const sourceUrl = this.sourceUrlInput ? this.normalizeSourceUrl(this.sourceUrlInput.value) : '';

        const VIDEO_EXT = ['.mp4', '.webm', '.mov', '.mkv', '.mpeg', '.mpg', '.m4v', '.avi'];

        if (!objective && !file && !sourceUrl) {
            this.addLog('Enter an objective and/or attach a file (PDF, DOCX, PPTX, video) and/or a project web link.', 'error');
            return;
        }

        let documentPayload = null;
        if (file) {
            const lower = file.name.toLowerCase();
            const isVideo = VIDEO_EXT.some((e) => lower.endsWith(e));
            const maxBytes = isVideo ? 50 * 1024 * 1024 : 6 * 1024 * 1024;
            if (file.size > maxBytes) {
                this.addLog(isVideo ? 'Video must be 50 MB or smaller.' : 'Document must be 6 MB or smaller.', 'error');
                return;
            }
            if (
                !isVideo &&
                !lower.endsWith('.pdf') &&
                !lower.endsWith('.docx') &&
                !lower.endsWith('.pptx')
            ) {
                this.addLog('Supported uploads: .pdf, .docx, .pptx, or video (.mp4, .webm, .mov, …).', 'error');
                return;
            }
            const buf = await file.arrayBuffer();
            documentPayload = {
                documentBase64: this.arrayBufferToBase64(buf),
                documentName: file.name,
                documentMime: file.type || 'application/octet-stream',
            };
        }

        const maxForms = parseInt(this.maxFormsInput.value, 10) || 6;
        const maxParallel = parseInt(this.maxParallelInput.value, 10) || 2;

        this.isRunning = true;
        this.pipelineTotal = 0;
        this.pipelineDone = 0;
        this.updateUIState();
        const label = (() => {
            const bits = [];
            if (file) bits.push(file.name);
            if (sourceUrl) bits.push(`link: ${sourceUrl}`);
            if (bits.length && objective) return `Discover (${bits.join(' + ')}) + notes`;
            if (bits.length) return `Discover from ${bits.join(' + ')}`;
            return `Discover forms — ${objective}`;
        })();
        this.addLog(label, 'user');

        try {
            const response = await chrome.runtime.sendMessage({
                type: 'RUN_PIPELINE',
                mode: 'discover_only',
                objective,
                maxForms,
                maxParallel,
                sourceUrl,
                documentSize: file ? file.size : undefined,
                ...(documentPayload || {}),
            });

            if (!response || !response.success) {
                throw new Error(response?.error || 'Discover failed');
            }

            const n = response.discovered != null ? response.discovered : 0;
            if (n === 0) {
                this.addLog('Discover: curator returned no forms.', 'system');
            } else {
                this.addLog(
                    `Discover complete: ${n} form(s) saved locally. Use Fill from last discovery to open tabs when ready.`,
                    'system'
                );
            }
            this.isRunning = false;
            this.updateUIState();
        } catch (error) {
            this.addLog(`Error: ${error.message}`, 'error');
            this.isRunning = false;
            this.pipelineTotal = 0;
            this.pipelineDone = 0;
            this.updateUIState();
        }
    }

    async runFillFromLastDiscovery() {
        const maxForms = parseInt(this.maxFormsInput.value, 10) || 6;
        const maxParallel = parseInt(this.maxParallelInput.value, 10) || 2;

        this.isRunning = true;
        this.pipelineTotal = 0;
        this.pipelineDone = 0;
        this.updateUIState();
        this.addLog('Fill from last discovery (opens tabs for saved form list)', 'user');

        try {
            const response = await chrome.runtime.sendMessage({
                type: 'RUN_FILL_FROM_LAST_DISCOVERY',
                maxForms,
                maxParallel,
            });

            if (!response || !response.success) {
                throw new Error(response?.error || 'Fill from discovery failed');
            }

            this.pipelineTotal = response.started || 0;
            this.pipelineDone = 0;

            if (this.pipelineTotal === 0) {
                this.addLog('No fill tabs started.', 'system');
                this.isRunning = false;
                this.updateUIState();
                return;
            }

            this.addLog(
                `${this.pipelineTotal} fill agent(s) running in parallel batches (local API + tabs).`,
                'system'
            );
        } catch (error) {
            this.addLog(`Error: ${error.message}`, 'error');
            this.isRunning = false;
            this.pipelineTotal = 0;
            this.pipelineDone = 0;
            this.updateUIState();
        }
    }

    pipelineMaybeFinish() {
        if (this.pipelineTotal <= 0) {
            return;
        }
        this.pipelineDone++;
        if (this.pipelineDone >= this.pipelineTotal) {
            this.addLog('Pipeline: all tab tasks finished', 'system');
            this.pipelineTotal = 0;
            this.pipelineDone = 0;
            this.isRunning = false;
        }
    }

    async remindUnfilledForTab(tabId, options = {}) {
        const fromAutoRemind = options.fromAutoRemind === true;
        if (tabId == null) {
            return;
        }
        try {
            const res = await chrome.runtime.sendMessage({
                type: 'GET_UNFILLED_REMINDER',
                tabId,
                highlight: true
            });
            if (!res || !res.success) {
                if (res && res.code === 'RESTRICTED_URL') {
                    if (fromAutoRemind) {
                        return;
                    }
                    this.addLog(
                        'Unfilled scan skipped: this tab is a browser-only page (New Tab, Extensions, about:blank, or a PDF viewer). Click into your application tab, then use Show unfilled fields.',
                        'system'
                    );
                    return;
                }
                if (res && res.error) {
                    this.addLog(`Unfilled reminder: ${res.error}`, 'error');
                }
                return;
            }
            const fields = res.fields || [];
            const totalFound = typeof res.totalFound === 'number' ? res.totalFound : fields.length;
            if (fields.length === 0) {
                this.addLog(
                    'Reminder: no empty fields matched our checklist on that tab. Still verify file uploads, CAPTCHAs, extra steps, and optional fields.',
                    'reminder'
                );
                return;
            }
            const lines = fields.slice(0, 14).map(
                (f) => `  • ${f.label}${f.required ? ' (required)' : ''}`
            );
            let body = `Reminder: ${totalFound} field(s) may still need input on that tab:\n${lines.join('\n')}`;
            if (totalFound > 14) {
                body += `\n  … and ${totalFound - 14} more (orange dashed outlines on the page)`;
            } else {
                body += '\nOrange dashed outlines mark these on the page.';
            }
            this.addLog(body, 'reminder');
        } catch (e) {
            this.addLog(`Unfilled reminder failed: ${e.message}`, 'error');
        }
    }

    async checkUnfilledThisTab() {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || tab.id == null) {
            this.addLog('No active tab to scan', 'error');
            return;
        }
        await this.remindUnfilledForTab(tab.id);
    }

    async stopAgent() {
        try {
            await chrome.runtime.sendMessage({ type: 'STOP_AGENT' });
            this.addLog('Stop requested (all active tasks)', 'system');
        } catch (error) {
            this.addLog(`Error stopping agent: ${error.message}`, 'error');
        }

        this.isRunning = false;
        this.pipelineTotal = 0;
        this.pipelineDone = 0;
        this.updateUIState();
    }

    updateUIState() {
        if (this.isRunning) {
            this.runBtn.disabled = true;
            this.runBtn.classList.add('loading');
            if (this.discoverFormsBtn) {
                this.discoverFormsBtn.disabled = true;
            }
            if (this.fillFromLastDiscoveryBtn) {
                this.fillFromLastDiscoveryBtn.disabled = true;
            }
            this.stopBtn.disabled = false;
            this.taskInput.disabled = true;
            if (this.projectFileInput) {
                this.projectFileInput.disabled = true;
            }
            if (this.sourceUrlInput) {
                this.sourceUrlInput.disabled = true;
            }
            if (this.pickProjectFileBtn) {
                this.pickProjectFileBtn.disabled = true;
            }
            if (this.clearFileBtn) {
                this.clearFileBtn.disabled = true;
            }
        } else {
            this.runBtn.disabled = false;
            this.runBtn.classList.remove('loading');
            if (this.discoverFormsBtn) {
                this.discoverFormsBtn.disabled = false;
            }
            if (this.fillFromLastDiscoveryBtn) {
                this.fillFromLastDiscoveryBtn.disabled = false;
            }
            this.stopBtn.disabled = true;
            this.taskInput.disabled = false;
            if (this.projectFileInput) {
                this.projectFileInput.disabled = false;
            }
            if (this.sourceUrlInput) {
                this.sourceUrlInput.disabled = false;
            }
            if (this.pickProjectFileBtn) {
                this.pickProjectFileBtn.disabled = false;
            }
            if (this.clearFileBtn) {
                this.clearFileBtn.disabled = false;
            }
        }
    }

    handleMessage(message) {
        switch (message.type) {
            case 'AGENT_LOG':
                break;
            case 'AGENT_COMPLETE':
                if (message.tabId != null) {
                    setTimeout(() => this.remindUnfilledForTab(message.tabId, { fromAutoRemind: true }), 450);
                }
                if (this.pipelineTotal > 0) {
                    this.pipelineMaybeFinish();
                } else {
                    this.isRunning = false;
                }
                this.updateUIState();
                break;
            case 'AGENT_ERROR': {
                if (message.tabId != null) {
                    setTimeout(() => this.remindUnfilledForTab(message.tabId, { fromAutoRemind: true }), 450);
                }
                if (this.pipelineTotal > 0) {
                    this.pipelineMaybeFinish();
                } else {
                    this.isRunning = false;
                }
                this.updateUIState();
                break;
            }
            case 'ACTION_EXECUTED':
                this.addLog(`Action: ${message.action}`, 'action');
                break;
        }
    }

    addLog(content, type = 'system') {
        // Logging disabled
    }
}

// Initialize popup controller
document.addEventListener('DOMContentLoaded', () => {
    new PopupController();
});
