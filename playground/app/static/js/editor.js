require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs' } });

let editor;

require(['vs/editor/editor.main'], function () {
    editor = monaco.editor.create(document.getElementById('monaco-editor'), {
        value: document.getElementById('sql-input')?.value || 'SELECT 1',
        language: 'sql',
        theme: window.matchMedia('(prefers-color-scheme: dark)').matches ? 'vs-dark' : 'vs',
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        automaticLayout: true,
        wordWrap: 'on',
    });

    // Ctrl+Enter submits
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, function () {
        document.getElementById('sql-input').value = editor.getValue();
        htmx.trigger('#query-form', 'submit');
    });
});

window.getEditorValue = function () {
    return editor ? editor.getValue() : '';
};

window.setEditorValue = function (val) {
    if (editor) editor.setValue(val);
};
