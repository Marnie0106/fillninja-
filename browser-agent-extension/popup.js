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

        this.isRunning = false;
        this.logs = [];

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

        // Quick action buttons
        this.quickActionBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt;
                this.taskInput.value = prompt;
                this.runAgent();
            });
        });

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
            this.statusText.textContent = 'Connected to AG2 Agent';
        } else {
            this.statusDot.classList.remove('connected');
            this.statusText.textContent = 'Disconnected - Start backend server';
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

            this.addLog('Agent started successfully', 'system');
        } catch (error) {
            this.addLog(`Error: ${error.message}`, 'error');
            this.isRunning = false;
            this.updateUIState();
        }
    }

    async stopAgent() {
        try {
            await chrome.runtime.sendMessage({ type: 'STOP_AGENT' });
            this.addLog('Agent stopped by user', 'system');
        } catch (error) {
            this.addLog(`Error stopping agent: ${error.message}`, 'error');
        }

        this.isRunning = false;
        this.updateUIState();
    }

    updateUIState() {
        if (this.isRunning) {
            this.runBtn.disabled = true;
            this.runBtn.classList.add('loading');
            this.stopBtn.disabled = false;
            this.taskInput.disabled = true;
        } else {
            this.runBtn.disabled = false;
            this.runBtn.classList.remove('loading');
            this.stopBtn.disabled = true;
            this.taskInput.disabled = false;
        }
    }

    handleMessage(message) {
        switch (message.type) {
            case 'AGENT_LOG':
                this.addLog(message.content, message.logType);
                break;
            case 'AGENT_COMPLETE':
                this.isRunning = false;
                this.updateUIState();
                this.addLog('Task completed successfully', 'system');
                break;
            case 'AGENT_ERROR':
                this.isRunning = false;
                this.updateUIState();
                this.addLog(`Agent error: ${message.error}`, 'error');
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
