const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const twemoji = fs.readFileSync('core/static/vendor/twemoji.min.js', 'utf8');
const common = fs.readFileSync('core/static/js/common.js', 'utf8');
const start = common.indexOf('function parsePageEmojis(');
const parser = common.slice(start, common.indexOf('function replaceEmojisWithFlagsHTML(', start));

test('emoji URLs use the SVG directory supplied by the bundled Twemoji parser', () => {
    const context = vm.createContext({ document: { body: {} } });
    context.window = context;
    vm.runInContext(twemoji + '\n' + parser, context);
    const parse = context.twemoji.parse;
    let html;
    context.twemoji.parse = (input, options) => { html = parse(input, options); };
    context.parsePageEmojis('☁ 🚀 🇷🇺');
    assert.ok(html.includes('https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/svg/2601.svg'));
    assert.ok(html.includes('https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/svg/1f680.svg'));
    assert.ok(html.includes('https://flagcdn.com/ru.svg'));
    assert.equal(html.includes('/undefined/'), false);
});
