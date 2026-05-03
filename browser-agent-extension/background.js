// FillNinja — background service worker (multi-tab / parallel agent tasks)

const LAST_DISCOVERY_KEY = 'fillninjaLastDiscovery';

function urlCannotRunUnfilledScan(url) {
    if (url == null) {
        return true;
    }
    const s = String(url);
    if (s === '') {
        return false;
    }
    const u = s.toLowerCase();
    return (
        u.startsWith('chrome://') ||
        u.startsWith('chrome-extension://') ||
        u.startsWith('about:') ||
        u.startsWith('devtools:') ||
        u.startsWith('chrome-untrusted://') ||
        u.startsWith('view-source:') ||
        u.startsWith('edge://') ||
        u.startsWith('brave://')
    );
}

class BackgroundController {
    constructor() {
        this.ag2BackendUrl = 'http://localhost:8000';
        this.isConnected = false;
        /** Set from GET /openapi.json — false when API is an older build without the prepare route */
        this.prepareApplicantContextAvailable = false;
        /** @type {Map<string, { tabId: number, eventSource: EventSource }>} */
        this.activeByTaskId = new Map();

        this.init();
    }

    init() {
        this.setupMessageListeners();
        this.checkBackendConnection();
        setInterval(() => this.checkBackendConnection(), 10000);
    }

    setupMessageListeners() {
        chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
            this.handleMessage(message, sender, sendResponse);
            return true;
        });
    }

    async handleMessage(message, sender, sendResponse) {
        try {
            switch (message.type) {
                case 'CHECK_STATUS':
                    sendResponse({
                        connected: this.isConnected,
                        prepareApplicantContextAvailable: this.prepareApplicantContextAvailable,
                    });
                    break;
                case 'RUN_AGENT':
                    await this.runAgent(message, sendResponse);
                    break;
                case 'PROFILE_DOCUMENT':
                    await this.profileDocumentOnServer(message, sendResponse);
                    break;
                case 'RUN_PIPELINE':
                    await this.runPipeline(message, sendResponse);
                    break;
                case 'RUN_FILL_FROM_LAST_DISCOVERY':
                    await this.runFillFromLastDiscovery(message, sendResponse);
                    break;
                case 'STOP_AGENT':
                    await this.stopAllAgents(sendResponse);
                    break;
                case 'GET_UNFILLED_REMINDER':
                    await this.getUnfilledReminder(message, sendResponse);
                    break;
                case 'CONTENT_SCRIPT_READY':
                    sendResponse({ received: true });
                    break;
                default:
                    sendResponse({ error: 'Unknown message type' });
            }
        } catch (error) {
            console.error('Background error:', error);
            sendResponse({ error: error.message });
        }
    }

    async checkBackendConnection() {
        this.prepareApplicantContextAvailable = false;
        try {
            const response = await fetch(`${this.ag2BackendUrl}/health`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });
            this.isConnected = response.ok;
            if (!response.ok) {
                return;
            }
            const ores = await fetch(`${this.ag2BackendUrl}/openapi.json`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });
            if (!ores.ok) {
                return;
            }
            const doc = await ores.json();
            const paths = doc.paths && typeof doc.paths === 'object' ? doc.paths : {};
            this.prepareApplicantContextAvailable = Object.prototype.hasOwnProperty.call(
                paths,
                '/agent/prepare_applicant_context',
            );
        } catch (error) {
            this.isConnected = false;
            this.prepareApplicantContextAvailable = false;
        }
    }

    sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    /** Human-readable HTTP error from POST /agent/prepare_applicant_context */
    prepareApplicantHttpError(status, detail, label) {
        const head = (label || 'Profiling failed') + ` (${status}): ${(detail || 'unknown').slice(0, 400)}`;
        if (status === 404) {
            return (
                head +
                ' The API you are hitting has no POST /agent/prepare_applicant_context (outdated process or wrong app on this port). From the FillNinja project directory, stop the old server and run: python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000'
            );
        }
        return head;
    }

    async profileDocumentOnServer(message, sendResponse) {
        if (!this.isConnected) {
            sendResponse({ success: false, error: 'FillNinja backend not connected.' });
            return;
        }
        if (!this.prepareApplicantContextAvailable) {
            sendResponse({
                success: false,
                error:
                    'This API build is too old: OpenAPI has no POST /agent/prepare_applicant_context. Stop every process on port 8000, then from your FillNinja folder run: python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000',
            });
            return;
        }
        const d64 = message.documentBase64 != null ? String(message.documentBase64).trim() : '';
        const dname = (message.documentName || '').trim();
        if (!d64 || !dname) {
            sendResponse({ success: false, error: 'Missing document' });
            return;
        }
        const ctx = message.applicantContext != null ? String(message.applicantContext).trim() : '';
        try {
            const res = await fetch(`${this.ag2BackendUrl}/agent/prepare_applicant_context`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    applicant_context: ctx || undefined,
                    document_base64: d64,
                    document_name: dname,
                }),
            });
            if (!res.ok) {
                let detail = '';
                try {
                    const j = await res.json();
                    if (j.detail != null) {
                        detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
                    } else {
                        detail = JSON.stringify(j);
                    }
                } catch (e) {
                    detail = await res.text();
                }
                sendResponse({
                    success: false,
                    error: this.prepareApplicantHttpError(res.status, detail, 'Profiling failed'),
                });
                return;
            }
            const data = await res.json();
            const applicantContext = String(data.applicant_context || '').trim();
            await chrome.storage.local.set({
                fillninjaLastUploadExtract: {
                    fileName: dname,
                    savedAt: new Date().toISOString(),
                    applicantContext,
                },
            });
            const maxUi = 8000;
            let extractBody =
                applicantContext ||
                '(No structured lines returned — the file may have no selectable text.)';
            if (applicantContext.length > maxUi) {
                extractBody =
                    applicantContext.slice(0, maxUi) +
                    `\n\n… ${applicantContext.length - maxUi} more characters. Full text: Service Worker console.`;
            }
            console.log('[FillNinja] Auto profile on upload (applicant_context):\n' + applicantContext);
            await this.notifyActivityLog(`Extracted after upload (${dname}):\n\n${extractBody}`, 'extract');
            sendResponse({ success: true, applicantContext });
        } catch (error) {
            sendResponse({
                success: false,
                error: error instanceof Error ? error.message : String(error),
            });
        }
    }

    async notifyActivityLog(content, logType = 'agent') {
        const entry = {
            timestamp: new Date().toLocaleTimeString(),
            content: String(content ?? ''),
            type: logType && String(logType).trim() ? String(logType).trim() : 'agent',
        };
        try {
            const data = await chrome.storage.local.get('agentLogs');
            const prev = Array.isArray(data.agentLogs) ? data.agentLogs : [];
            const next = [...prev, entry].slice(-100);
            await chrome.storage.local.set({ agentLogs: next });
        } catch (e) {
            console.warn('FillNinja notifyActivityLog', e);
        }
        this.broadcastToPopup({
            type: 'AGENT_LOG',
            content: entry.content,
            logType: entry.type,
        });
    }

    waitTabComplete(tabId) {
        return new Promise((resolve) => {
            const timeout = setTimeout(() => {
                chrome.tabs.onUpdated.removeListener(listener);
                resolve();
            }, 35000);

            function listener(id, info) {
                if (id === tabId && info.status === 'complete') {
                    clearTimeout(timeout);
                    chrome.tabs.onUpdated.removeListener(listener);
                    resolve();
                }
            }

            chrome.tabs.onUpdated.addListener(listener);
            chrome.tabs.get(tabId, (tab) => {
                if (chrome.runtime.lastError) {
                    return;
                }
                if (tab && tab.status === 'complete') {
                    clearTimeout(timeout);
                    chrome.tabs.onUpdated.removeListener(listener);
                    resolve();
                }
            });
        });
    }

    async runAgent(message, sendResponse) {
        if (!this.isConnected) {
            sendResponse({
                success: false,
                error: 'FillNinja backend not connected. Start the API server (uvicorn).'
            });
            return;
        }

        try {
            await this.startAgentOnTab(message.tabId, message.task, {
                applicantContext: message.applicantContext,
                documentBase64: message.documentBase64,
                documentName: message.documentName,
            });
            sendResponse({ success: true });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    async startAgentOnTab(tabId, task, extras = {}) {
        let applicantContext = extras.applicantContext != null ? String(extras.applicantContext).trim() : '';
        const documentBase64 = extras.documentBase64;
        const documentName = extras.documentName;
        const d64 = documentBase64 != null ? String(documentBase64).trim() : '';
        const dname = documentName != null ? String(documentName).trim() : '';

        if (d64 && dname) {
            if (this.prepareApplicantContextAvailable) {
                const prep = await fetch(`${this.ag2BackendUrl}/agent/prepare_applicant_context`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        applicant_context: applicantContext || undefined,
                        document_base64: d64,
                        document_name: dname,
                    }),
                });
                if (!prep.ok) {
                    let detail = '';
                    try {
                        const j = await prep.json();
                        detail = j.detail != null ? String(j.detail) : JSON.stringify(j);
                    } catch (e) {
                        detail = await prep.text();
                    }
                    throw new Error(
                        this.prepareApplicantHttpError(prep.status, detail, 'Résumé profiling failed'),
                    );
                }
                const prepData = await prep.json();
                applicantContext = String(prepData.applicant_context || '').trim();
                console.log(
                    '[FillNinja] Extracted from résumé (applicant_context):\n' + (applicantContext || '(empty)'),
                );

                const maxUi = 8000;
                let extractBody =
                    applicantContext ||
                    '(No structured lines returned — the PDF may have no selectable text, or the model left fields empty.)';
                if (applicantContext.length > maxUi) {
                    extractBody =
                        applicantContext.slice(0, maxUi) +
                        `\n\n… ${applicantContext.length - maxUi} more characters. Full text is in the Service Worker console (chrome://extensions → FillNinja → Service worker).`;
                }
                await this.notifyActivityLog(`Extracted from résumé:\n\n${extractBody}`, 'extract');

                await this.notifyActivityLog(
                    'Continuing: reading the active tab for the form (use an https:// page, not chrome://).',
                    'system',
                );
            }
        }

        try {
            await this.executeOnTab(tabId, { action: 'CLEAR_UNFILLED_HIGHLIGHTS' });
        } catch (e) {
            /* tab may not have content script yet */
        }
        const pageInfo = await this.executeOnTab(tabId, { action: 'GET_PAGE_INFO' });
        const domSnapshot = await this.executeOnTab(tabId, { action: 'GET_DOM_SNAPSHOT' });

        const payload = {
            task,
            page_info: pageInfo.result,
            dom_snapshot: domSnapshot.result,
            tab_id: tabId,
        };
        if (applicantContext) {
            payload.applicant_context = applicantContext;
        }
        if (d64 && dname && !this.prepareApplicantContextAvailable) {
            payload.document_base64 = d64;
            payload.document_name = dname;
        }

        const response = await fetch(`${this.ag2BackendUrl}/agent/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error(`Backend error: ${response.status}`);
        }

        const data = await response.json();
        const taskId = data.task_id;
        this.attachEventStream(taskId, tabId);
        return taskId;
    }

    attachEventStream(taskId, tabId) {
        const prev = this.activeByTaskId.get(taskId);
        if (prev && prev.eventSource) {
            prev.eventSource.close();
        }

        const eventSource = new EventSource(`${this.ag2BackendUrl}/agent/${taskId}/events`);
        this.activeByTaskId.set(taskId, { tabId, eventSource });

        eventSource.onmessage = async (event) => {
            const payload = JSON.parse(event.data);
            await this.handleAgentEvent(payload, taskId, tabId);
        };

        eventSource.onerror = () => {
            this.teardownTask(taskId);
            this.broadcastToPopup({
                type: 'AGENT_ERROR',
                error: 'Connection to agent lost',
                taskId
            });
        };
    }

    async startFillAgentsForForms(forms, maxForms, maxParallel) {
        const limit = Math.min(forms.length, maxForms);
        if (limit <= 0) {
            return 0;
        }
        this.broadcastToPopup({
            type: 'PIPELINE_FILL_COUNT',
            total: limit,
            logType: 'pipeline'
        });

        for (let i = 0; i < limit; i += maxParallel) {
            const batch = forms.slice(i, i + maxParallel);
            await Promise.all(
                batch.map(async (item, j) => {
                    const tab = await chrome.tabs.create({
                        url: item.url,
                        active: i === 0 && j === 0
                    });
                    await this.waitTabComplete(tab.id);
                    await this.sleep(700);
                    try {
                        await this.startAgentOnTab(tab.id, item.fill_task);
                        await this.notifyActivityLog(
                            `Fill agent started: ${item.title || item.url}`,
                            'pipeline',
                        );
                    } catch (e) {
                        await this.notifyActivityLog(
                            `Fill failed for ${item.url}: ${e.message}`,
                            'error',
                        );
                    }
                })
            );
        }
        return limit;
    }

    async runFillFromLastDiscovery(message, sendResponse) {
        if (!this.isConnected) {
            sendResponse({
                success: false,
                error: 'FillNinja backend not connected.'
            });
            return;
        }
        try {
            const stored = await chrome.storage.local.get(LAST_DISCOVERY_KEY);
            const rec = stored[LAST_DISCOVERY_KEY];
            if (!rec || !Array.isArray(rec.forms) || rec.forms.length === 0) {
                sendResponse({
                    success: false,
                    error: 'No saved discovery with forms. Run Discover forms first.',
                });
                return;
            }
            const maxForms = Math.min(
                Math.max(parseInt(message.maxForms, 10) || rec.maxFormsRequested || 6, 1),
                20
            );
            const maxParallel = Math.min(Math.max(parseInt(message.maxParallel, 10) || 2, 1), 6);
            await this.notifyActivityLog(
                `Fill from last discovery: ${rec.forms.length} form(s) on file; opening up to ${maxForms} tab(s).`,
                'pipeline',
            );
            const started = await this.startFillAgentsForForms(rec.forms, maxForms, maxParallel);
            sendResponse({ success: true, started });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    async runPipeline(message, sendResponse) {
        if (!this.isConnected) {
            sendResponse({
                success: false,
                error: 'FillNinja backend not connected.'
            });
            return;
        }

        const mode = message.mode === 'discover_only' ? 'discover_only' : 'discover_and_fill';
        const objective = (message.objective || '').trim();
        const maxForms = Math.min(Math.max(parseInt(message.maxForms, 10) || 6, 1), 20);
        const maxParallel = Math.min(Math.max(parseInt(message.maxParallel, 10) || 2, 1), 6);

        const docB64 = message.documentBase64;
        const docName = (message.documentName || '').trim();
        const hasDoc = Boolean(docB64 && docName);
        const sourceUrl = (message.sourceUrl || '').trim();
        const hasUrl = Boolean(sourceUrl);
        const needsMultipart = hasDoc || hasUrl;

        if (!objective && !hasDoc && !hasUrl) {
            sendResponse({
                success: false,
                error: 'Pipeline objective is empty and no document or URL was provided',
            });
            return;
        }

        try {
            let res;
            if (needsMultipart) {
                const form = new FormData();
                if (hasDoc) {
                    const binary = atob(docB64);
                    const bytes = new Uint8Array(binary.length);
                    for (let i = 0; i < binary.length; i++) {
                        bytes[i] = binary.charCodeAt(i);
                    }
                    const blob = new Blob([bytes], { type: message.documentMime || 'application/octet-stream' });
                    form.append('file', blob, docName);
                }
                form.append('objective', objective);
                form.append('max_forms', String(maxForms));
                if (hasUrl) {
                    form.append('source_url', sourceUrl);
                }
                res = await fetch(`${this.ag2BackendUrl}/pipeline/discover_from_document`, {
                    method: 'POST',
                    body: form,
                });
            } else {
                res = await fetch(`${this.ag2BackendUrl}/pipeline/discover`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ objective, max_forms: maxForms }),
                });
            }

            if (!res.ok) {
                const t = await res.text();
                throw new Error(`Discover failed ${res.status}: ${t.slice(0, 200)}`);
            }

            const data = await res.json();
            const forms = data.forms || [];
            const materialId = `disc-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

            let formsStarted = 0;
            const formsStartedCap = Math.min(forms.length, maxForms);
            if (forms.length > 0) {
                formsStarted = mode === 'discover_only' ? 0 : formsStartedCap;
            }

            if (data.project_profile && data.project_profile.summary) {
                await this.notifyActivityLog(
                    `Profile from your materials — ${data.project_profile.summary}`,
                    'curator',
                );
            }

            const factsRaw =
                typeof data.applicant_context_for_forms === 'string'
                    ? data.applicant_context_for_forms.trim()
                    : '';
            if (factsRaw) {
                const maxUi = 8000;
                let extractBody = factsRaw;
                if (extractBody.length > maxUi) {
                    extractBody =
                        extractBody.slice(0, maxUi) +
                        `\n\n… ${factsRaw.length - maxUi} more characters. Full text is in the Service Worker console (chrome://extensions → FillNinja → Service worker).`;
                }
                console.log(
                    '[FillNinja] Extracted from discover upload (applicant_context_for_forms):\n' + factsRaw,
                );
                await this.notifyActivityLog(`Extracted from your PDF/document:\n\n${extractBody}`, 'extract');
            }

            await this.notifyActivityLog(
                data.summary || `Curator returned ${forms.length} candidate form(s).`,
                'curator',
            );

            if (forms.length === 0) {
                try {
                    await chrome.storage.local.remove(LAST_DISCOVERY_KEY);
                } catch (e) {
                    /* ignore */
                }
                sendResponse({ success: true, started: 0, discovered: 0, mode });
                return;
            }

            await chrome.storage.local.set({
                [LAST_DISCOVERY_KEY]: {
                    materialId,
                    savedAt: new Date().toISOString(),
                    forms,
                    maxFormsRequested: maxForms,
                    objective,
                    sourceUrl: sourceUrl || '',
                },
            });

            if (mode === 'discover_only') {
                sendResponse({
                    success: true,
                    started: 0,
                    discovered: forms.length,
                    mode,
                });
                return;
            }

            const started = await this.startFillAgentsForForms(forms, formsStartedCap, maxParallel);
            sendResponse({ success: true, started, discovered: forms.length, mode });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    teardownTask(taskId) {
        const rec = this.activeByTaskId.get(taskId);
        if (rec && rec.eventSource) {
            rec.eventSource.onerror = null;
            rec.eventSource.close();
        }
        this.activeByTaskId.delete(taskId);
    }

    async stopAllAgents(sendResponse) {
        if (this.activeByTaskId.size === 0) {
            sendResponse({ success: false, error: 'No active tasks' });
            return;
        }

        try {
            const ids = Array.from(this.activeByTaskId.keys());
            for (const taskId of ids) {
                try {
                    await fetch(`${this.ag2BackendUrl}/agent/${taskId}/stop`, {
                        method: 'POST'
                    });
                } catch (e) {
                    /* ignore */
                }
                this.teardownTask(taskId);
            }
            sendResponse({ success: true });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    async handleAgentEvent(event, taskId, tabId) {
        if (event.log) {
            await this.notifyActivityLog(event.log, event.log_type || 'agent');
        }

        if (event.action) {
            this.broadcastToPopup({
                type: 'ACTION_EXECUTED',
                action: event.action.type,
                taskId
            });

            try {
                const execResult = await this.executeOnTab(tabId, {
                    action: event.action.type,
                    ...event.action.params
                });

                await fetch(`${this.ag2BackendUrl}/agent/${taskId}/action-result`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action_id: event.action.id,
                        result: execResult.result,
                        error: execResult.error
                    })
                });
            } catch (error) {
                await fetch(`${this.ag2BackendUrl}/agent/${taskId}/action-result`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action_id: event.action.id,
                        error: error.message
                    })
                });
            }
        }

        if (event.type === 'complete') {
            this.teardownTask(taskId);
            await this.notifyActivityLog('Tab task completed', 'system');
            this.broadcastToPopup({ type: 'AGENT_COMPLETE', taskId, tabId });
        }

        if (event.type === 'error') {
            this.teardownTask(taskId);
            const err = event.error || '';
            const isCancel = err === 'Task cancelled' || err === 'stopped';
            await this.notifyActivityLog(
                isCancel ? 'Stopped (you cancelled the run)' : `Agent error: ${err}`,
                isCancel ? 'system' : 'error',
            );
            this.broadcastToPopup({
                type: 'AGENT_ERROR',
                error: event.error,
                taskId,
                tabId
            });
        }
    }

    async getUnfilledReminder(message, sendResponse) {
        const highlight = message.highlight !== false;
        let tabId = message.tabId;
        try {
            if (tabId == null) {
                const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
                tabId = tab?.id;
            }
            if (!tabId) {
                sendResponse({ success: false, error: 'No tab' });
                return;
            }
            const tab = await chrome.tabs.get(tabId);
            const u = tab.url || '';
            if (urlCannotRunUnfilledScan(u)) {
                sendResponse({
                    success: false,
                    code: 'RESTRICTED_URL',
                    error:
                        'This tab cannot be scanned (browser-internal page). Switch to your https:// form tab and use Show unfilled fields.',
                });
                return;
            }
            const res = await this.executeOnTab(tabId, {
                action: 'GET_UNFILLED_FIELDS',
                highlight
            });
            if (!res || !res.success) {
                sendResponse({
                    success: false,
                    error: res?.error || 'Could not scan page (try refreshing the tab).'
                });
                return;
            }
            sendResponse({ success: true, ...res.result });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    async ensureContentScript(tabId) {
        await chrome.scripting.executeScript({
            target: { tabId },
            files: ['content.js'],
        });
    }

    async executeOnTab(tabId, message) {
        const send = () =>
            new Promise((resolve, reject) => {
                chrome.tabs.sendMessage(tabId, message, (response) => {
                    if (chrome.runtime.lastError) {
                        reject(new Error(chrome.runtime.lastError.message));
                    } else {
                        resolve(response);
                    }
                });
            });
        try {
            return await send();
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            if (!msg.includes('Receiving end does not exist')) {
                throw err;
            }
            try {
                await this.ensureContentScript(tabId);
            } catch (injectErr) {
                const detail =
                    injectErr instanceof Error ? injectErr.message : String(injectErr);
                throw new Error(
                    `Cannot use FillNinja on this page (${detail}). Open a normal http(s) tab, refresh it, and try again.`,
                );
            }
            return await send();
        }
    }

    broadcastToPopup(message) {
        chrome.runtime.sendMessage(message).catch(() => {});
    }
}

new BackgroundController();
