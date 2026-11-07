/* Exercise real UI handlers with a minimal DOM, without browser/network writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.isConnected = true; }
  append(...nodes) { this.children.push(...nodes); }
  prepend(...nodes) { this.children.unshift(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute() {}
}
function elements(root) { return [root, ...root.children.flatMap(n => n instanceof Element ? elements(n) : [])]; }
const source = fs.readFileSync('services/douyin/publishing/ui.js', 'utf8');
function fixture({failure = false, unknown = false, networkFailure = false, bothPlatforms = false, voiceFailure = true} = {}) {
  const target = {platform:'douyin', status:'generated', publish_status:unknown ? 'unknown' : 'failed',
    publication:{message:voiceFailure ? '成稿口吻不符：cards[3].text 含旁观转述“作者认为”' : '未取得发布回执'}, content:{}};
  const batch = {id:'old-version', history_id:'source-history', created_at:1, targets:[target]};
  if (bothPlatforms) batch.targets.push({...target, platform:'xiaohongshu'});
  const container = new Element('section'), calls = [], timers = [], window = {};
  let posts = 0, reads = 0;
  const context = {window, location:{pathname:'/tabs/douyin/understanding/source-history'},
    document:{createElement:tag => new Element(tag), head:new Element('head'), getElementById:() => null},
    setTimeout:fn => { timers.push(fn); return fn; }, clearTimeout:() => {},
    fetch:async (path, options = {}) => {
      calls.push({path, options});
      if (path.endsWith('/capabilities')) return {ok:true, json:async () => ({version:2, douyin:{music_required:true, text_validation:true, relayout:true}})};
      if (options.method === 'POST') {
        posts++;
        if (networkFailure && posts === 1) throw Error('connection lost');
        return {ok:true, json:async () => ({batch_id:'new-version', created:true})};
      }
      reads++;
      const running = reads === 1;
      return {ok:true, json:async () => ({publications:[{...batch, id:'new-version', auto_publish:true,
        status:running ? 'running' : failure ? 'error' : 'done',
        targets:[{...target, status:running ? 'running' : failure ? 'error' : 'generated',
          error:failure ? '模型口吻校验失败' : '', publish_status:running ? 'not_connected' : failure ? 'not_connected' : 'published'}]}, ...(bothPlatforms ? [batch] : [])]})};
    }};
  vm.runInNewContext(source, context);
  window.PublicationUI.render(container, [batch]);
  const button = label => elements(container).find(n => n.tagName === 'button' && n.textContent === label);
  return {container, calls, timers, button};
}
(async () => {
  for (const auto of [false, true]) {
    const f = fixture();
    assert.equal(f.button('重新发送到抖音图文').disabled, true);
    await f.button(auto ? '重新生成并发布到抖音图文' : '重新生成内容').onclick();
    const call = f.calls.find(c => c.options.method === 'POST');
    assert.equal(call.path, '/tabs/douyin/api/understanding-history/source-history/publications');
    const data = JSON.parse(call.options.body);
    assert.deepEqual(data.platforms, ['douyin']);
    assert.equal(data.auto_publish, auto);
    assert.match(data.request_id, /^regenerate_/);
    assert.equal(f.timers.length, 1);
    await f.timers.shift()();
    assert.equal(f.timers.length, 0);
    assert.ok(elements(f.container).some(n => n.textContent?.includes('内容已发布')));
    assert.ok(!f.calls.some(c => /\/send$/.test(c.path)));
  }
  const retry = fixture({networkFailure:true});
  await retry.button('重新生成并发布到抖音图文').onclick();
  await retry.button('重新生成并发布到抖音图文').onclick();
  const requests = retry.calls.filter(c => c.options.method === 'POST').map(c => JSON.parse(c.options.body));
  assert.equal(requests[0].request_id, requests[1].request_id, 'lost response must reuse idempotency key');
  const failed = fixture({failure:true});
  await failed.button('重新生成并发布到抖音图文').onclick();
  await failed.timers.shift()();
  assert.equal(failed.timers.length, 0);
  assert.ok(elements(failed.container).some(n => n.textContent === '模型口吻校验失败'));
  const unknown = fixture({unknown:true, voiceFailure:false});
  assert.equal(unknown.button('重新发送到抖音图文').disabled, false);
  assert.ok(!elements(unknown.container).some(n => n.textContent?.includes('发布结果待核实')));
  const both = fixture({bothPlatforms:true});
  assert.equal(both.container.children[0].className, 'publication-platform-overview');
  assert.ok(elements(both.container.children[0]).some(n => n.textContent === '重新生成并发布到小红书'));
  await both.button('重新生成并发布到抖音图文').onclick();
  assert.ok(elements(both.container.children[0]).some(n => n.textContent?.includes('各平台可独立提交')));
  function currentXhs() {
    const version = both.container.children.find(n => n.children.some(card => card.children?.some(s => s.textContent?.startsWith('小红书 · 当前版本'))));
    assert.ok(version, 'latest XHS remains present in the older batch');
    assert.equal(version.open, true, 'older batch containing latest XHS must stay expanded');
    const card = version.children.find(n => n.children?.some(s => s.textContent?.startsWith('小红书 · 当前版本')));
    assert.equal(card.open, true, 'latest XHS controls must stay visible');
    return elements(card).find(n => n.textContent === '重新生成并发布到小红书');
  }
  assert.equal(currentXhs().disabled, false, 'Douyin generation must not disable XHS regeneration');
  await both.timers.shift()();
  assert.equal(currentXhs().disabled, false, 'XHS action reactivates after Douyin completes');
  console.log('Publication regeneration UI tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
