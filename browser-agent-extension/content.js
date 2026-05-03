// AG2 Browser Agent - Content Script
// This script runs in the context of web pages and provides DOM interaction capabilities

class PageInteractor {
    constructor() {
        this.highlightedElements = [];
        this.observers = new Map();
    }

    // Get comprehensive page information
    getPageInfo() {
        return {
            url: window.location.href,
            title: document.title,
            domain: window.location.hostname,
            scrollPosition: { x: window.scrollX, y: window.scrollY },
            viewport: { width: window.innerWidth, height: window.innerHeight },
            documentHeight: document.documentElement.scrollHeight,
            documentWidth: document.documentElement.scrollWidth
        };
    }

    // Get structured DOM information
    getDOMSnapshot() {
        const snapshot = {
            forms: this.getForms(),
            links: this.getLinks(),
            buttons: this.getButtons(),
            inputs: this.getInputs(),
            headings: this.getHeadings(),
            images: this.getImages(),
            tables: this.getTables(),
            textContent: this.getVisibleText()
        };
        return snapshot;
    }

    getForms() {
        return Array.from(document.querySelectorAll('form')).map((form, index) => ({
            index,
            id: form.id || null,
            action: form.action || null,
            method: form.method || 'get',
            fields: Array.from(form.querySelectorAll('input, select, textarea')).map(field => ({
                tag: field.tagName.toLowerCase(),
                type: field.type || null,
                name: field.name || null,
                id: field.id || null,
                placeholder: field.placeholder || null,
                required: field.required,
                value: field.value || null,
                label: this.getFieldLabel(field)
            }))
        }));
    }

    getFieldLabel(field) {
        // Try to find associated label
        if (field.id) {
            const label = document.querySelector(`label[for="${field.id}"]`);
            if (label) return label.textContent.trim();
        }
        // Check parent label
        const parentLabel = field.closest('label');
        if (parentLabel) {
            return parentLabel.textContent.trim().replace(field.value || '', '').trim();
        }
        // Check aria-label
        return field.getAttribute('aria-label') || null;
    }

    getLinks() {
        return Array.from(document.querySelectorAll('a[href]')).map((link, index) => ({
            index,
            href: link.href,
            text: link.textContent.trim().slice(0, 100),
            title: link.title || null,
            isVisible: this.isElementVisible(link)
        })).filter(l => l.text || l.title);
    }

    getButtons() {
        return Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], [role="button"]')).map((btn, index) => ({
            index,
            tag: btn.tagName.toLowerCase(),
            type: btn.type || null,
            text: btn.textContent?.trim().slice(0, 50) || btn.value || null,
            id: btn.id || null,
            className: btn.className || null,
            isVisible: this.isElementVisible(btn)
        }));
    }

    getInputs() {
        return Array.from(document.querySelectorAll('input, textarea, select')).map((input, index) => ({
            index,
            tag: input.tagName.toLowerCase(),
            type: input.type || null,
            name: input.name || null,
            id: input.id || null,
            placeholder: input.placeholder || null,
            value: input.value || null,
            isVisible: this.isElementVisible(input)
        }));
    }

    getHeadings() {
        return Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6')).map((h, index) => ({
            index,
            level: parseInt(h.tagName[1]),
            text: h.textContent.trim().slice(0, 200)
        }));
    }

    getImages() {
        return Array.from(document.querySelectorAll('img')).map((img, index) => ({
            index,
            src: img.src,
            alt: img.alt || null,
            width: img.naturalWidth,
            height: img.naturalHeight,
            isVisible: this.isElementVisible(img)
        }));
    }

    getTables() {
        return Array.from(document.querySelectorAll('table')).map((table, index) => ({
            index,
            rows: Array.from(table.querySelectorAll('tr')).slice(0, 10).map(row =>
                Array.from(row.querySelectorAll('td, th')).map(cell => cell.textContent.trim())
            ),
            caption: table.querySelector('caption')?.textContent?.trim() || null
        }));
    }

    getVisibleText() {
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        const textNodes = [];
        let node;
        while (node = walker.nextNode()) {
            if (this.isElementVisible(node.parentElement)) {
                const text = node.textContent.trim();
                if (text.length > 20) {
                    textNodes.push(text);
                }
            }
        }

        return textNodes.slice(0, 50);
    }

    isElementVisible(element) {
        if (!element) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 &&
               rect.height > 0 &&
               rect.top < window.innerHeight &&
               rect.bottom > 0 &&
               rect.left < window.innerWidth &&
               rect.right > 0;
    }

    // Actions

    async click(selectorOrIndex, type = 'button') {
        let element;

        if (typeof selectorOrIndex === 'number') {
            const elements = document.querySelectorAll(type === 'button' ? 'button, [role="button"]' : 'a');
            element = elements[selectorOrIndex];
        } else {
            element = document.querySelector(selectorOrIndex);
        }

        if (!element) {
            throw new Error(`Element not found: ${selectorOrIndex}`);
        }

        this.highlightElement(element);

        // Scroll into view
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        await this.sleep(500);

        // Click
        element.click();

        return { success: true, action: 'click', element: this.describeElement(element) };
    }

    async fill(selectorOrIndex, value, type = 'input') {
        let element;

        if (typeof selectorOrIndex === 'number') {
            const elements = document.querySelectorAll('input, textarea, select');
            element = elements[selectorOrIndex];
        } else {
            element = document.querySelector(selectorOrIndex);
        }

        if (!element) {
            throw new Error(`Input not found: ${selectorOrIndex}`);
        }

        this.highlightElement(element);

        // Scroll into view
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        await this.sleep(300);

        // Focus and clear
        element.focus();
        element.value = '';

        // Type value
        element.value = value;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));

        return { success: true, action: 'fill', value, element: this.describeElement(element) };
    }

    async select(selectorOrIndex, optionText) {
        let element;

        if (typeof selectorOrIndex === 'number') {
            const elements = document.querySelectorAll('select');
            element = elements[selectorOrIndex];
        } else {
            element = document.querySelector(selectorOrIndex);
        }

        if (!element) {
            throw new Error(`Select not found: ${selectorOrIndex}`);
        }

        this.highlightElement(element);

        // Find option
        const options = Array.from(element.options);
        const option = options.find(o =>
            o.text.toLowerCase().includes(optionText.toLowerCase()) ||
            o.value.toLowerCase().includes(optionText.toLowerCase())
        );

        if (!option) {
            throw new Error(`Option "${optionText}" not found`);
        }

        element.value = option.value;
        element.dispatchEvent(new Event('change', { bubbles: true }));

        return { success: true, action: 'select', option: option.text };
    }

    async scroll(direction = 'down', amount = 500) {
        const scrollOptions = {
            top: direction === 'down' ? window.scrollY + amount : window.scrollY - amount,
            left: window.scrollX,
            behavior: 'smooth'
        };

        window.scrollTo(scrollOptions);
        await this.sleep(500);

        return { success: true, action: 'scroll', direction, newPosition: { x: window.scrollX, y: window.scrollY } };
    }

    async navigate(url) {
        window.location.href = url;
        return { success: true, action: 'navigate', url };
    }

    async waitForElement(selector, timeout = 5000) {
        return new Promise((resolve, reject) => {
            const element = document.querySelector(selector);
            if (element) {
                resolve({ success: true, found: true });
                return;
            }

            const observer = new MutationObserver(() => {
                const element = document.querySelector(selector);
                if (element) {
                    observer.disconnect();
                    resolve({ success: true, found: true });
                }
            });

            observer.observe(document.body, { childList: true, subtree: true });

            setTimeout(() => {
                observer.disconnect();
                reject(new Error(`Timeout waiting for element: ${selector}`));
            }, timeout);
        });
    }

    async sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    highlightElement(element) {
        // Remove previous highlights
        this.clearHighlights();

        // Add highlight
        const originalOutline = element.style.outline;
        const originalBoxShadow = element.style.boxShadow;

        element.style.outline = '3px solid #667eea';
        element.style.boxShadow = '0 0 10px rgba(102, 126, 234, 0.5)';
        element.style.transition = 'outline 0.3s, box-shadow 0.3s';

        this.highlightedElements.push({ element, originalOutline, originalBoxShadow });

        // Auto-clear after 3 seconds
        setTimeout(() => this.clearHighlights(), 3000);
    }

    clearHighlights() {
        this.highlightedElements.forEach(({ element, originalOutline, originalBoxShadow }) => {
            element.style.outline = originalOutline;
            element.style.boxShadow = originalBoxShadow;
        });
        this.highlightedElements = [];
    }

    describeElement(element) {
        return {
            tag: element.tagName.toLowerCase(),
            id: element.id || null,
            className: element.className || null,
            text: element.textContent?.trim().slice(0, 100) || null
        };
    }

    // Extract data based on a query
    extractData(query) {
        // Simple extraction based on common patterns
        const results = [];

        // Try to find elements matching the query
        const selectors = [
            `[data-testid*="${query}"]`,
            `[class*="${query}"]`,
            `[id*="${query}"]`,
            `*:contains("${query}")`
        ];

        for (const selector of selectors) {
            try {
                const elements = document.querySelectorAll(selector);
                elements.forEach(el => {
                    if (this.isElementVisible(el)) {
                        results.push({
                            text: el.textContent.trim(),
                            html: el.innerHTML.slice(0, 500)
                        });
                    }
                });
            } catch (e) {
                // Invalid selector, skip
            }
        }

        return results;
    }
}

// Initialize interactor
const interactor = new PageInteractor();

// Listen for messages from background script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    const handleAction = async () => {
        try {
            let result;

            switch (message.action) {
                case 'GET_PAGE_INFO':
                    result = interactor.getPageInfo();
                    break;

                case 'GET_DOM_SNAPSHOT':
                    result = interactor.getDOMSnapshot();
                    break;

                case 'CLICK':
                    result = await interactor.click(message.selector, message.elementType);
                    break;

                case 'FILL':
                    result = await interactor.fill(message.selector, message.value, message.elementType);
                    break;

                case 'SELECT':
                    result = await interactor.select(message.selector, message.optionText);
                    break;

                case 'SCROLL':
                    result = await interactor.scroll(message.direction, message.amount);
                    break;

                case 'NAVIGATE':
                    result = await interactor.navigate(message.url);
                    break;

                case 'WAIT_FOR_ELEMENT':
                    result = await interactor.waitForElement(message.selector, message.timeout);
                    break;

                case 'EXTRACT_DATA':
                    result = interactor.extractData(message.query);
                    break;

                case 'GET_VISIBLE_TEXT':
                    result = interactor.getVisibleText();
                    break;

                default:
                    throw new Error(`Unknown action: ${message.action}`);
            }

            sendResponse({ success: true, result });
        } catch (error) {
            sendResponse({ success: false, error: error.message });
        }
    };

    handleAction();
    return true; // Keep channel open for async
});

// Notify that content script is ready
chrome.runtime.sendMessage({ type: 'CONTENT_SCRIPT_READY', url: window.location.href });
