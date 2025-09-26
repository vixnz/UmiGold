// src/extension.ts
import * as vscode from 'vscode';
import WebSocket from 'ws'; // ensure "esModuleInterop": true in tsconfig.json
import { TextDocument, Range } from 'vscode';

/**
 * Types expected from backend. Adjust these to match your backend schema.
 */
type Location = { start_line: number; end_line: number; start_col?: number; end_col?: number };
type RefactorItem = {
    id: string;
    title: string;
    location: Location;
    patched_code: string;
    description?: string;
};
type RefactorSuggestion = { file_path: string; items: RefactorItem[] };
type Vulnerability = { type: string; description: string; line: number; file_path?: string };
type ContextAnalyzerPayload = { file_path: string; vulnerabilities: Vulnerability[] };

/**
 * Configuration
 */
const AI_BACKEND_URL = "wss://ai-engine.example.com/ws"; // replace with your backend
const INITIAL_RECONNECT_MS = 1000;
const MAX_RECONNECT_MS = 60_000;
const DOCUMENT_DEBOUNCE_MS = 300; // debounce sending edits to backend

/**
 * Helper: debounce
 */
function debounce<T extends (...args: any[]) => void>(fn: T, wait = 200) {
    let timer: NodeJS.Timeout | null = null;
    return (...args: Parameters<T>) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
    };
}

/**
 * Unified code actions provider that returns quick fixes based on a suggestion map.
 */
class AISuggestionProvider implements vscode.CodeActionsProvider {
    constructor(private suggestionMap: Map<string, RefactorItem[]>) { }

    public provideCodeActions(document: vscode.TextDocument, range: vscode.Range): vscode.ProviderResult<vscode.CodeAction[]> {
        const filePath = document.uri.fsPath;
        const items = this.suggestionMap.get(filePath);
        if (!items || items.length === 0) return [];

        const actions: vscode.CodeAction[] = [];
        for (const s of items) {
            // Build suggestion range
            const start = new vscode.Position(Math.max(0, s.location.start_line - 1), s.location.start_col ?? 0);
            const end = new vscode.Position(Math.max(0, s.location.end_line - 1), s.location.end_col ?? Number.MAX_VALUE);
            const suggestionRange = new vscode.Range(start, end);

            // Only show actions that overlap the requested range (keeps UI relevant)
            if (!range.intersection(suggestionRange)) continue;

            const quickFix = new vscode.CodeAction(`Optimize: ${s.title}`, vscode.CodeActionKind.QuickFix);
            const edit = new vscode.WorkspaceEdit();
            edit.replace(document.uri, suggestionRange, s.patched_code);
            quickFix.edit = edit;
            quickFix.isPreferred = true;

            // Attach command that notifies backend when applied
            quickFix.command = {
                title: 'Apply AI Fix',
                command: 'ai.applyFix',
                arguments: [s.id, document.uri.fsPath]
            };

            actions.push(quickFix);
        }
        return actions;
    }
}

/**
 * Extension activation
 */
export function activate(context: vscode.ExtensionContext) {
    let socket: WebSocket | null = null;
    let reconnectDelay = INITIAL_RECONNECT_MS;
    let reconnectTimer: NodeJS.Timeout | null = null;
    const diagnosticCollection = vscode.languages.createDiagnosticCollection('ai-assistant');
    const suggestionMap = new Map<string, RefactorItem[]>(); // file_path -> suggestions[]
    const diagnosticsPerFile = new Map<string, vscode.Diagnostic[]>();
    const docChangeTimers = new Map<string, NodeJS.Timeout | null>();

    // Register provider once
    const provider = new AISuggestionProvider(suggestionMap);
    context.subscriptions.push(vscode.languages.registerCodeActionsProvider({ scheme: 'file' }, provider));

    // Register applyFix command (notifying backend)
    context.subscriptions.push(vscode.commands.registerCommand('ai.applyFix', async (suggestionId: string, filePath: string) => {
        // Apply is handled by VS Code workspace edit already. Notify backend if socket open
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ action: 'ACCEPTED', suggestion_id: suggestionId, file_path: filePath }));
        }
    }));

    // Register reject command (optional)
    context.subscriptions.push(vscode.commands.registerCommand('ai.rejectFix', (suggestionId: string, filePath: string) => {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ action: 'REJECTED', suggestion_id: suggestionId, file_path: filePath }));
        }
    }));

    /**
     * Connect with exponential backoff
     */
    function connect() {
        if (socket) {
            try { socket.removeAllListeners?.(); socket.close(); } catch { /* ignore */ }
            socket = null;
        }

        socket = new WebSocket(AI_BACKEND_URL);

        socket.on('open', () => {
            reconnectDelay = INITIAL_RECONNECT_MS;
            vscode.window.showInformationMessage('AI Assistant connected');
            // Optionally send handshake / auth
            // socket.send(JSON.stringify({ action: 'HELLO', token: ... }));
        });

        socket.on('message', (data: WebSocket.Data) => {
            // data can be Buffer, string, etc.
            try {
                const text = typeof data === 'string' ? data : data.toString();
                const payload = JSON.parse(text);

                // Distinguish types heuristically
                if (payload && payload.items && Array.isArray(payload.items)) {
                    handleRefactorSuggestions(payload as RefactorSuggestion);
                } else if (payload && payload.vulnerabilities) {
                    updateContextDiagnostics(payload as ContextAnalyzerPayload);
                } else {
                    console.warn('Unknown AI payload format', payload);
                }
            } catch (err) {
                console.error('Failed parsing AI payload', err);
            }
        });

        socket.on('close', (code?: number, reason?: Buffer) => {
            vscode.window.showWarningMessage('AI Assistant disconnected — reconnecting...');
            scheduleReconnect();
        });

        socket.on('error', (err: any) => {
            console.error('AI WebSocket error', err);
            // socket will usually emit close after error
        });
    }

    function scheduleReconnect() {
        if (reconnectTimer) return; // already scheduled
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_MS);
            connect();
        }, reconnectDelay);
    }

    /**
     * Handle incoming refactor suggestions
     */
    function handleRefactorSuggestions(suggestions: RefactorSuggestion) {
        const file = suggestions.file_path;
        // Replace the suggestion list for that file
        suggestionMap.set(file, suggestions.items);
        // Trigger provider UI refresh by updating diagnostics (VSCode doesn't need explicit refresh for providers)
        // We also set a context key or show a notification if desired
        // Optionally show a non-intrusive info
        if (suggestions.items.length > 0) {
            vscode.window.setStatusBarMessage(`AI: ${suggestions.items.length} suggestions for ${file}`, 3000);
        }
    }

    /**
     * Update vulnerability diagnostics. Keeps diagnostics per file.
     */
    function updateContextDiagnostics(payload: ContextAnalyzerPayload) {
        const fileUri = vscode.Uri.file(payload.file_path);
        const diagnostics: vscode.Diagnostic[] = [];
        for (const vuln of payload.vulnerabilities) {
            const start = new vscode.Position(Math.max(0, vuln.line - 1), 0);
            const end = new vscode.Position(Math.max(0, vuln.line - 1), Number.MAX_VALUE);
            const range = new vscode.Range(start, end);
            const diag = new vscode.Diagnostic(range, `[SECURITY] ${vuln.type}: ${vuln.description}`, vscode.DiagnosticSeverity.Warning);
            diag.source = 'AI Assistant';
            diagnostics.push(diag);
        }
        diagnosticsPerFile.set(payload.file_path, diagnostics);
        diagnosticCollection.set(fileUri, diagnostics);
    }

    /**
     * Debounced document change sender
     */
    const sendDocumentToBackend = debounce((doc: TextDocument) => {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        const payload = {
            file_path: doc.uri.fsPath,
            content: doc.getText(),
            version: doc.version,
            languageId: doc.languageId
        };
        try {
            socket.send(JSON.stringify(payload));
        } catch (e) {
            console.error('Failed sending document to AI backend', e);
        }
    }, DOCUMENT_DEBOUNCE_MS);

    // Listen to document changes
    context.subscriptions.push(vscode.workspace.onDidChangeTextDocument(event => {
        // Only send for files (not untitled) and when socket open
        if (!event.document.uri || event.document.isUntitled) return;
        sendDocumentToBackend(event.document);
    }));

    // Also send file on save to ensure server has latest
    context.subscriptions.push(vscode.workspace.onDidSaveTextDocument((doc) => {
        if (!doc.uri || doc.isUntitled) return;
        // send immediately (not debounced)
        if (socket && socket.readyState === WebSocket.OPEN) {
            try {
                socket.send(JSON.stringify({
                    file_path: doc.uri.fsPath,
                    content: doc.getText(),
                    version: doc.version,
                    event: 'save'
                }));
            } catch (e) {
                console.error('Failed sending saved document to AI backend', e);
            }
        }
    }));

    // Provide a command to request suggestions for the active file on demand
    context.subscriptions.push(vscode.commands.registerCommand('ai.requestSuggestions', () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !socket || socket.readyState !== WebSocket.OPEN) {
            vscode.window.showWarningMessage('AI backend not connected or no active editor');
            return;
        }
        const payload = {
            action: 'REQUEST_SUGGESTIONS',
            file_path: editor.document.uri.fsPath,
            content: editor.document.getText()
        };
        socket.send(JSON.stringify(payload));
    }));

    // When the user opens a file, register diagnostics and ensure suggestions are available
    context.subscriptions.push(vscode.workspace.onDidOpenTextDocument((doc) => {
        // re-set diagnostics for the file if we have them
        const diagnostics = diagnosticsPerFile.get(doc.uri.fsPath);
        if (diagnostics) diagnosticCollection.set(doc.uri, diagnostics);
    }));

    // Clean up on deactivate
    context.subscriptions.push({
        dispose: () => {
            try {
                diagnosticCollection.clear();
                diagnosticCollection.dispose();
                if (socket) {
                    socket.close();
                    socket = null;
                }
                if (reconnectTimer) {
                    clearTimeout(reconnectTimer);
                    reconnectTimer = null;
                }
            } catch (e) {
                console.error('Error during extension dispose', e);
            }
        }
    });

    // Kick off connection
    connect();
}

/**
 * Deactivate hook
 */
export function deactivate() {
    // Nothing specific here: dispose handlers added in activate will run
}
