// AG2 Browser Agent - Popup Script

class PopupController {
    constructor() {
        this.taskInput = document.getElementById('taskInput');
        this.runBtn = document.getElementById('runBtn');
        this.stopBtn = document.getElementById('stopBtn');
        this.clearBtn = document.getElementById('clearBtn');
        this.settingsBtn = document.getElementById('settingsBtn');
        this.logsContainer = document.getElementById('logsContainer');
        this.statusDot = document.getElementById('statusDot');
        this.statusText = document.getElementById('statusText');
        this.quickActionBtns = document.querySelectorAll('.quick-action-btn');
        this.pipelineBtn = document.getElementById('pipelineBtn');
        this.maxFormsInput = document.getElementById('maxFormsInput');
        this.maxParallelInput = document.getElementById('maxParallelInput');
        this.projectFileInput = document.getElementById('projectFileInput');
        this.clearFileBtn = document.getElementById('clearFileBtn');
        this.sourceUrlInput = document.getElementById('sourceUrlInput');
        this.pickProjectFileBtn = document.getElementById('pickProjectFileBtn');
        this.unfilledReminderBtn = document.getElementById('unfilledReminderBtn');

        this.isRunning = false;
        this.logs = [];
        this.pipelineTotal = 0;
        this.pipelineDone = 0;

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.checkConnectionStatus();
        this.loadLogs();

        // Check status periodically
        setInterval(() => this.checkConnectionStatus(), 5000);
    }

    setupEventListeners() {
        // Run button
        this.runBtn.addEventListener('click', () => this.runAgent());

        // Stop button
        this.stopBtn.addEventListener('click', () => this.stopAgent());

        // Clear logs button
        this.clearBtn.addEventListener('click', () => this.clearLogs());

        // Settings button
        this.settingsBtn.addEventListener('click', () => this.openSettings());

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

        this.pipelineBtn.addEventListener('click', () => this.runPipeline());

        if (this.pickProjectFileBtn && this.projectFileInput) {
            this.pickProjectFileBtn.addEventListener('click', () => this.projectFileInput.click());
        }

        if (this.clearFileBtn && this.projectFileInput && this.sourceUrlInput) {
            this.clearFileBtn.addEventListener('click', () => {
                this.projectFileInput.value = '';
                this.sourceUrlInput.value = '';
            });
        } else if (this.clearFileBtn && this.projectFileInput) {
            this.clearFileBtn.addEventListener('click', () => {
                this.projectFileInput.value = '';
            });
        }

        // Listen for messages from background script
        chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
            this.handleMessage(message);
            sendResponse({ received: true });
        });
    }

    async checkConnectionStatus() {
        try {
            const response = await chrome.runtime.sendMessage({ type: 'CHECK_STATUS' });
            if (response && response.connected) {
                this.setConnected(true);
            } else {
                this.setConnected(false);
            }
        } catch (error) {
            this.setConnected(false);
        }
    }

    setConnected(connected) {
        if (connected) {
            this.statusDot.classList.add('connected');
            this.statusText.textContent = 'Connected to FillNinja backend';
        } else {
            this.statusDot.classList.remove('connected');
            this.statusText.textContent = 'Disconnected — start the Python server';
        }
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

        try {
            // Get current tab info
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

            const response = await chrome.runtime.sendMessage({
                type: 'RUN_AGENT',
                task: task,
                tabId: tab.id,
                url: tab.url,
                title: tab.title
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

    async runPipeline() {
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
            if (bits.length && objective) return `Pipeline (${bits.join(' + ')}) + notes`;
            if (bits.length) return `Pipeline from ${bits.join(' + ')}`;
            return `Pipeline: discovering forms for — ${objective}`;
        })();
        this.addLog(label, 'user');

        try {
            const response = await chrome.runtime.sendMessage({
                type: 'RUN_PIPELINE',
                objective,
                maxForms,
                maxParallel,
                sourceUrl,
                ...(documentPayload || {}),
            });

            if (!response || !response.success) {
                throw new Error(response?.error || 'Pipeline failed to start');
            }

            this.pipelineTotal = response.started || 0;
            this.pipelineDone = 0;

            if (this.pipelineTotal === 0) {
                this.addLog('Pipeline: no forms to fill (curator returned empty)', 'system');
                this.isRunning = false;
                this.updateUIState();
                return;
            }

            this.addLog(`${this.pipelineTotal} fill agent(s) running in parallel batches`, 'system');
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

    async remindUnfilledForTab(tabId) {
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
            this.pipelineBtn.disabled = true;
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
            this.pipelineBtn.disabled = false;
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
                this.addLog(message.content, message.logType);
                break;
            case 'AGENT_COMPLETE':
                this.addLog('Tab task completed', 'system');
                if (message.tabId != null) {
                    setTimeout(() => this.remindUnfilledForTab(message.tabId), 450);
                }
                if (this.pipelineTotal > 0) {
                    this.pipelineMaybeFinish();
                } else {
                    this.isRunning = false;
                }
                this.updateUIState();
                break;
            case 'AGENT_ERROR':
                this.addLog(`Agent error: ${message.error}`, 'error');
                if (message.tabId != null) {
                    setTimeout(() => this.remindUnfilledForTab(message.tabId), 450);
                }
                if (this.pipelineTotal > 0) {
                    this.pipelineMaybeFinish();
                } else {
                    this.isRunning = false;
                }
                this.updateUIState();
                break;
            case 'ACTION_EXECUTED':
                this.addLog(`Action: ${message.action}`, 'action');
                break;
        }
    }

    addLog(content, type = 'system') {
        const timestamp = new Date().toLocaleTimeString();
        const logEntry = { timestamp, content, type };

        this.logs.push(logEntry);

        // Keep only last 100 logs
        if (this.logs.length > 100) {
            this.logs = this.logs.slice(-100);
        }

        this.saveLogs();
        this.renderLogs();
    }

    renderLogs() {
        if (this.logs.length === 0) {
            this.logsContainer.innerHTML = '<div class="empty-state">No activity yet. Start by entering a task above.</div>';
            return;
        }

        this.logsContainer.innerHTML = this.logs.map(log => `
            <div class="log-entry ${log.type}">
                <span class="timestamp">${log.timestamp}</span>
                ${this.escapeHtml(log.content)}
            </div>
        `).join('');

        // Auto-scroll to bottom
        this.logsContainer.scrollTop = this.logsContainer.scrollHeight;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clearLogs() {
        this.logs = [];
        this.saveLogs();
        this.renderLogs();
    }

    async saveLogs() {
        await chrome.storage.local.set({ agentLogs: this.logs });
    }

    async loadLogs() {
        const result = await chrome.storage.local.get('agentLogs');
        if (result.agentLogs) {
            this.logs = result.agentLogs;
            this.renderLogs();
        }
    }

    openSettings() {
        chrome.tabs.create({ url: chrome.runtime.getURL('settings.html') });
    }
}

// Initialize popup controller
document.addEventListener('DOMContentLoaded', () => {
    new PopupController();
});
