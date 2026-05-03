// AG2 Browser Agent - Background Service Worker
// Handles communication between popup, content scripts, and the AG2 backend

class BackgroundController {
    constructor() {
        this.ag2BackendUrl = 'http://localhost:8000';
        this.isConnected = false;
        this.currentTask = null;
        this.eventSource = null;

        this.init();
    }

    init() {
        this.setupMessageListeners();
        this.checkBackendConnection();

        // Periodically check connection
        setInterval(() => this.checkBackendConnection(), 10000);
    }

    setupMessageListeners() {
        chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
            this.handleMessage(message, sender, sendResponse);
            return true; // Keep channel open for async
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

                case 'STOP_AGENT':
                    await this.stopAgent(sendResponse);
                    break;

                case 'CONTENT_SCRIPT_READY':
                    console.log('Content script ready on:', message.url);
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

    async runAgent(message, sendResponse) {
        if (!this.isConnected) {
            sendResponse({
                success: false,
                error: 'FillNinja backend not connected. Start the API server (uvicorn).'
            });
            return;
        }

        try {
            // Get page information first
            const pageInfo = await this.executeOnTab(message.tabId, {
                action: 'GET_PAGE_INFO'
            });

            // Get DOM snapshot
            const domSnapshot = await this.executeOnTab(message.tabId, {
                action: 'GET_DOM_SNAPSHOT'
            });

            // Start the agent task
            const response = await fetch(`${this.ag2BackendUrl}/agent/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    task: message.task,
                    page_info: pageInfo.result,
                    dom_snapshot: domSnapshot.result,
                    tab_id: message.tabId
                })
            });

            if (!response.ok) {
                throw new Error(`Backend error: ${response.status}`);
            }

            const data = await response.json();
            this.currentTask = {
                taskId: data.task_id,
                tabId: message.tabId
            };

            // Start listening for agent events
            this.listenToAgentEvents(data.task_id);

            sendResponse({ success: true, taskId: data.task_id });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    async stopAgent(sendResponse) {
        if (!this.currentTask) {
            sendResponse({ success: false, error: 'No active task' });
            return;
        }

        try {
            await fetch(`${this.ag2BackendUrl}/agent/${this.currentTask.taskId}/stop`, {
                method: 'POST'
            });

            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }

            this.currentTask = null;
            sendResponse({ success: true });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    }

    listenToAgentEvents(taskId) {
        if (this.eventSource) {
            this.eventSource.close();
        }

        this.eventSource = new EventSource(`${this.ag2BackendUrl}/agent/${taskId}/events`);

        this.eventSource.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            await this.handleAgentEvent(data);
        };

        this.eventSource.onerror = () => {
            this.broadcastToPopup({
                type: 'AGENT_ERROR',
                error: 'Connection to agent lost'
            });
            this.eventSource.close();
        };
    }

    async handleAgentEvent(event) {
        // Forward log to popup
        if (event.log) {
            this.broadcastToPopup({
                type: 'AGENT_LOG',
                content: event.log,
                logType: event.log_type || 'agent'
            });
        }

        // Handle actions that need to be executed on the page
        if (event.action && this.currentTask) {
            this.broadcastToPopup({
                type: 'ACTION_EXECUTED',
                action: event.action.type
            });

            try {
                const result = await this.executeOnTab(this.currentTask.tabId, {
                    action: event.action.type,
                    ...event.action.params
                });

                // Send result back to backend
                await fetch(`${this.ag2BackendUrl}/agent/${this.currentTask.taskId}/action-result`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action_id: event.action.id,
                        result: result.result,
                        error: result.error
                    })
                });
            } catch (error) {
                await fetch(`${this.ag2BackendUrl}/agent/${this.currentTask.taskId}/action-result`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action_id: event.action.id,
                        error: error.message
                    })
                });
            }
        }

        // Handle completion
        if (event.type === 'complete') {
            this.broadcastToPopup({ type: 'AGENT_COMPLETE' });
            this.currentTask = null;
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
        }

        // Handle errors
        if (event.type === 'error') {
            this.broadcastToPopup({
                type: 'AGENT_ERROR',
                error: event.error
            });
        }
    }

    async executeOnTab(tabId, message) {
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
        chrome.runtime.sendMessage(message).catch(() => {
            // Popup might be closed, ignore error
        });
    }
}

// Initialize background controller
new BackgroundController();
