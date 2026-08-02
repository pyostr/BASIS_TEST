"""Регистрация страницы документации Scalar API."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from scalar_fastapi import (
    AgentScalarConfig,
    Layout,
    OpenAPISource,
    get_scalar_api_reference,
)

from src.config.settings import Settings

# CSS кнопки генерации UUIDv7 в поле заголовка ``Idempotency-Key``.
# Scalar рендерит заголовки как строки таблицы: ``<tr id="Idempotency-Key">``,
# где редактируемое поле значения — ``.code-input-lite__editor``.
# Отступ справа резервирует место под нашу кнопку, чтобы текст не перекрывался.
_UUID7_STYLE = """
<style>
tr#Idempotency-Key td:last-child .code-input-lite__editor {
    padding-right: 2.4rem;
}
.scalar-uuid7-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    padding: 0;
    margin: 0 1px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--scalar-color-2, #888);
    cursor: pointer;
}
.scalar-uuid7-btn:hover {
    background: var(--scalar-background-2, #eee);
    color: var(--scalar-color-1, #222);
}
</style>
"""

# Скрипт встраивает кнопку генерации UUIDv7 (RFC 9562) в ячейку значения
# заголовка ``Idempotency-Key``. У Scalar нет нативного механизма генерации,
# поэтому дополняем страницу собственным JS-кодом.
#
# Строка параметра рендерится как ``<tr id="Idempotency-Key" class="group">``,
# а поле значения — как contenteditable-элемент ``.code-input-lite__editor``
# с aria-label ``"<label> Value"``. Значение подставляется напрямую в DOM,
# после чего эмулируется событие ``input``: Scalar читает контент обратно в
# модель (serializeEditor) и обновляет заголовок запроса.
_UUID7_SCRIPT = """
<script>
(function () {
    'use strict';

    function uuid7() {
        var bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);
        var ts = BigInt(Date.now());
        bytes[0] = Number((ts >> 40n) & 0xffn);
        bytes[1] = Number((ts >> 32n) & 0xffn);
        bytes[2] = Number((ts >> 24n) & 0xffn);
        bytes[3] = Number((ts >> 16n) & 0xffn);
        bytes[4] = Number((ts >> 8n) & 0xffn);
        bytes[5] = Number(ts & 0xffn);
        bytes[6] = (bytes[6] & 0x0f) | 0x70;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        var hex = Array.from(bytes, function (b) {
            return b.toString(16).padStart(2, '0');
        }).join('');
        return [
            hex.slice(0, 8),
            hex.slice(8, 12),
            hex.slice(12, 16),
            hex.slice(16, 20),
            hex.slice(20),
        ].join('-');
    }

    function findIdempotencyRow() {
        var row = document.getElementById('Idempotency-Key');
        if (row && row.tagName === 'TR') {
            return row;
        }
        var editors = document.querySelectorAll('.code-input-lite__editor');
        for (var i = 0; i < editors.length; i++) {
            var text = (editors[i].textContent || '').trim();
            if (/^idempotency[\\s_-]*key$/i.test(text)) {
                var tr = editors[i].closest('tr');
                if (tr) {
                    return tr;
                }
            }
        }
        return null;
    }

    function getValueEditor(row) {
        var valueEditor = row.querySelector(
            '.code-input-lite__editor[aria-label$=" Value"]'
        );
        if (valueEditor) {
            return valueEditor;
        }
        var editors = row.querySelectorAll('.code-input-lite__editor');
        return editors.length > 1 ? editors[1] : null;
    }

    function setValue(editor, value) {
        editor.focus();
        while (editor.firstChild) {
            editor.removeChild(editor.firstChild);
        }
        editor.appendChild(document.createTextNode(value));
        var event;
        if (typeof InputEvent === 'function') {
            event = new InputEvent('input', {
                bubbles: true,
                inputType: 'insertText',
                data: value,
            });
        } else {
            event = new Event('input', { bubbles: true });
        }
        editor.dispatchEvent(event);
        editor.blur();
    }

    function decorateRow(row) {
        if (row.dataset.uuid7Button) {
            return;
        }
        row.dataset.uuid7Button = '1';
        var editor = getValueEditor(row);
        if (!editor) {
            return;
        }
        var cell = editor.closest('td');
        if (!cell) {
            return;
        }
        var container =
            cell.querySelector('div.centered-y.absolute.right-0') || cell;
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'scalar-uuid7-btn';
        button.title = 'Generate UUID7';
        button.setAttribute('aria-label', 'Generate UUID7');
        button.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" ' +
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M21 12a9 9 0 1 1-2.64-6.36"/>' +
            '<polyline points="21 3 21 9 15 9"/></svg>';
        button.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            var target = getValueEditor(row);
            if (target) {
                setValue(target, uuid7());
            }
        });
        container.appendChild(button);
    }

    var observer = new MutationObserver(function () {
        var row = findIdempotencyRow();
        if (row) {
            decorateRow(row);
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    var initial = findIdempotencyRow();
    if (initial) {
        decorateRow(initial);
    }
})();
</script>
"""


def _inject_uuid7_button(page: str) -> str:
    """Встраивает стили и скрипт кнопки генерации UUIDv7 в HTML-страницу Scalar."""
    page = page.replace('</head>', _UUID7_STYLE + '</head>')
    page = page.replace('</body>', _UUID7_SCRIPT + '</body>')
    return page


def register_scalar_route(app: FastAPI, settings: Settings) -> None:
    """Регистрирует маршрут ``/scalar``, отдающий страницу справочника OpenAPI."""

    @app.get('/scalar', include_in_schema=False)
    async def scalar_html():
        """Отдаёт страницу справочника Scalar API для схемы OpenAPI."""
        reference = get_scalar_api_reference(
            title=settings.APP_NAME,
            sources=[
                OpenAPISource(
                    title='API Платежей',
                    url='/openapi.json',
                    default=True,
                    agent=AgentScalarConfig(disabled=True),
                ),
            ],
            layout=Layout.MODERN,
            show_sidebar=True,
            # Подставлять X-API-Key: dev-key в тестовые запросы (для удобства).
            authentication={
                'preferredSecurityScheme': 'XApiKey',
                'securitySchemes': {
                    'XApiKey': {
                        'type': 'apiKey',
                        'in': 'header',
                        'name': 'X-API-Key',
                        'value': 'dev-key',
                    },
                },
            },
        )
        page = reference.body.decode('utf-8')
        return HTMLResponse(content=_inject_uuid7_button(page))
