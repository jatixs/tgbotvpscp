const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const bootstrapSource = fs.readFileSync('core/static/js/panel_bootstrap.js', 'utf8');

test('applyPanelBootstrap parses JSON i18n from data attribute and populates window.I18N', () => {
    const document = {
        querySelector(sel) {
            if (sel === 'main[data-panel-page]') {
                return {
                    dataset: {
                        panelPage: 'nodes',
                        panelKey: 'test-key',
                        panelRole: 'owner',
                        panelRoleLevel: '10',
                        panelOwner: 'true',
                        panelI18n: '{"web_cpu":"ЦП","web_ram":"ОЗУ","web_disk":"Диск","web_node_details":"Подробнее"}',
                        panelBilling: '{"balance": 100}',
                        panelPingMode: 'http'
                    },
                    getAttribute(attr) {
                        if (attr === 'data-panel-i18n') {
                            return '{"web_cpu":"ЦП","web_ram":"ОЗУ","web_disk":"Диск","web_node_details":"Подробнее"}';
                        }
                        if (attr === 'data-panel-billing') return '{"balance": 100}';
                        return null;
                    }
                };
            }
            return null;
        }
    };

    const ctx = vm.createContext({
        document,
        window: {},
        Number,
        JSON,
        Object
    });
    ctx.window = ctx;

    vm.runInContext(bootstrapSource, ctx);

    assert.equal(ctx.window.I18N.web_cpu, 'ЦП');
    assert.equal(ctx.window.I18N.web_ram, 'ОЗУ');
    assert.equal(ctx.window.I18N.web_disk, 'Диск');
    assert.equal(ctx.window.I18N.web_node_details, 'Подробнее');
    assert.equal(ctx.window.WEB_KEY, 'test-key');
    assert.equal(ctx.window.USER_ROLE, 'owner');
    assert.equal(ctx.window.USER_ROLE_LEVEL, 10);
    assert.equal(ctx.window.IS_MAIN_ADMIN, true);
});

test('applyPanelBootstrap handles double-encoded JSON strings gracefully', () => {
    const document = {
        querySelector(sel) {
            if (sel === 'main[data-panel-page]') {
                return {
                    dataset: {
                        panelPage: 'nodes',
                        panelI18n: JSON.stringify('{"web_cpu":"ЦП"}')
                    },
                    getAttribute(attr) {
                        if (attr === 'data-panel-i18n') return JSON.stringify('{"web_cpu":"ЦП"}');
                        return null;
                    }
                };
            }
            return null;
        }
    };

    const ctx = vm.createContext({
        document,
        window: {},
        Number,
        JSON,
        Object
    });
    ctx.window = ctx;

    vm.runInContext(bootstrapSource, ctx);

    assert.equal(ctx.window.I18N.web_cpu, 'ЦП');
});
