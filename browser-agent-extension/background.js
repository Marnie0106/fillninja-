// FillNinja — background service worker (multi-tab / parallel agent tasks)

class BackgroundController {
    constructor() {
        this.ag2BackendUrl = 'http://localhost:8000';
        this.isConnected = false;
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
                    sendResponse({ connected: this.isConnected });
                    break;
                case 'RUN_AGENT':
                    await this.runAgent(message, sendResponse);
                    break;
                case 'RUN_PIPELINE':
                    await this.runPipeline(message, sendResponse);
                    break;
                case 'STOP_AGENT':
                    await this.stopAllAgents(sendResponse);
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
        try {
            const response = await fetch(`${this.ag2BackendUrl}/health`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });
            this.isConnected = response.ok;
        } catch (error) {
            this.isConnected = false;
        }
    }

    sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
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
            await this.startAgentOnTab(message.tabId, message.task);
            sendResponse({ success: true });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    async startAgentOnTab(tabId, task) {
        const pageInfo = await this.executeOnTab(tabId, { action: 'GET_PAGE_INFO' });
        const domSnapshot = await this.executeOnTab(tabId, { action: 'GET_DOM_SNAPSHOT' });

        const response = await fetch(`${this.ag2BackendUrl}/agent/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task,
                page_info: pageInfo.result,
                dom_snapshot: domSnapshot.result,
                tab_id: tabId
            })
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

    async runPipeline(message, sendResponse) {
        if (!this.isConnected) {
            sendResponse({
                success: false,
                error: 'FillNinja backend not connected.'
            });
            return;
        }

        const objective = (message.objective || '').trim();
        const maxForms = Math.min(Math.max(parseInt(message.maxForms, 10) || 6, 1), 20);
        const maxParallel = Math.min(Math.max(parseInt(message.maxParallel, 10) || 2, 1), 6);

        if (!objective) {
            sendResponse({ success: false, error: 'Pipeline objective is empty' });
            return;
        }

        try {
            const res = await fetch(`${this.ag2BackendUrl}/pipeline/discover`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ objective, max_forms: maxForms })
            });

            if (!res.ok) {
                const t = await res.text();
                throw new Error(`Discover failed ${res.status}: ${t.slice(0, 200)}`);
            }

            const data = await res.json();
            const forms = data.forms || [];

            this.broadcastToPopup({
                type: 'AGENT_LOG',
                content: data.summary || `Curator returned ${forms.length} candidate form(s).`,
                logType: 'curator'
            });

            if (forms.length === 0) {
                sendResponse({ success: true, started: 0 });
                return;
            }

            const limit = Math.min(forms.length, maxForms);
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
                            this.broadcastToPopup({
                                type: 'AGENT_LOG',
                                content: `Fill agent started: ${item.title || item.url}`,
                                logType: 'pipeline'
                            });
                        } catch (e) {
                            this.broadcastToPopup({
                                type: 'AGENT_LOG',
                                content: `Fill failed for ${item.url}: ${e.message}`,
                                logType: 'error'
                            });
                        }
                    })
                );
            }

            sendResponse({ success: true, started: limit });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    teardownTask(taskId) {
        const rec = this.activeByTaskId.get(taskId);
        if (rec && rec.eventSource) {
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
            this.broadcastToPopup({
                type: 'AGENT_LOG',
                content: event.log,
                logType: event.log_type || 'agent',
                taskId
            });
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
            this.broadcastToPopup({ type: 'AGENT_COMPLETE', taskId });
        }

        if (event.type === 'error') {
            this.teardownTask(taskId);
            this.broadcastToPopup({
                type: 'AGENT_ERROR',
                error: event.error,
                taskId
            });
        }
    }

    executeOnTab(tabId, message) {
        return new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tabId, message, (response) => {
                if (chrome.runtime.lastError) {
                    reject(new Error(chrome.runtime.lastError.message));
                } else {
                    resolve(response);
                }
            });
        });
    }

    broadcastToPopup(message) {
        chrome.runtime.sendMessage(message).catch(() => {});
    }
}

new BackgroundController();
