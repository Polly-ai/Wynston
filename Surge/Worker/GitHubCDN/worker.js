// GitHub CDN 加速 Worker - 部署到 Cloudflare Workers
// 用法:
//   https://github-cdn.mimingzhe.workers.dev/https://raw.githubusercontent.com/user/repo/main/file.js
//   https://github-cdn.mimingzhe.workers.dev/raw.githubusercontent.com/user/repo/main/file.js
//   https://github-cdn.mimingzhe.workers.dev/https://gist.githubusercontent.com/user/<gist-id>/raw/file.py
//   https://github-cdn.mimingzhe.workers.dev/gist.githubusercontent.com/user/<gist-id>/raw/file.py
//   https://github-cdn.mimingzhe.workers.dev/https://github.com/user/repo/releases/download/v1.0/file.zip
//   https://github-cdn.mimingzhe.workers.dev/https://codeload.github.com/user/repo/tar.gz/refs/tags/v1.0
//
// 只允许以下 GitHub 相关域名, 其他一律 403, 防止被当成通用代理滥用.
// raw / gist 是本次的核心, github.com 仅放行 raw / releases/download / archive,
// codeload / objects / release-assets 仅用于 release / archive 的实际文件下载.

const ALLOWED_HOSTS = new Set([
  'raw.githubusercontent.com',
  'gist.githubusercontent.com',
  'gist.github.com',
  'github.com',
  'codeload.github.com',
  'objects.githubusercontent.com',
  'github-releases.githubusercontent.com',
  'release-assets.githubusercontent.com',
]);

// github.com 只放行这几种路径前缀
function isAllowedGithubComPath(pathname) {
  return (
    pathname.includes('/raw/') ||
    pathname.includes('/releases/download/') ||
    pathname.includes('/archive/')
  );
}

function parseTarget(requestUrl) {
  // 去掉开头的 /
  let rest = requestUrl.pathname.slice(1);
  if (requestUrl.search) rest += requestUrl.search;

  // 兼容 /https://... 和 /http://... 两种写法
  if (rest.startsWith('https://') || rest.startsWith('http://')) {
    return new URL(rest);
  }
  // 兼容 /raw.githubusercontent.com/... 这种不带协议的写法
  // rest 的第一段就是 host
  const firstSlash = rest.indexOf('/');
  if (firstSlash === -1) return null;
  const host = rest.slice(0, firstSlash);
  if (!ALLOWED_HOSTS.has(host)) return null;
  return new URL('https://' + rest);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 首页: 使用说明, 方便部署后直接打开验证
    if (url.pathname === '/' || url.pathname === '') {
      return new Response(
        'GitHub CDN Worker is running.\n\n' +
        'Usage:\n' +
        '  /https://raw.githubusercontent.com/<user>/<repo>/<branch>/<file>\n' +
        '  /raw.githubusercontent.com/<user>/<repo>/<branch>/<file>\n' +
        '  /https://gist.githubusercontent.com/<user>/<gist-id>/raw/<file>\n' +
        '  /gist.githubusercontent.com/<user>/<gist-id>/raw/<file>\n',
        { status: 200, headers: { 'content-type': 'text/plain; charset=utf-8' } }
      );
    }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method Not Allowed', { status: 405 });
    }

    let target;
    try {
      target = parseTarget(url);
    } catch {
      return new Response('Bad Request', { status: 400 });
    }
    if (!target) {
      return new Response('Not Found', { status: 404 });
    }

    if (!ALLOWED_HOSTS.has(target.hostname)) {
      return new Response('Forbidden: host not allowed', { status: 403 });
    }
    if (target.hostname === 'github.com' && !isAllowedGithubComPath(target.pathname)) {
      return new Response('Forbidden: only raw / releases / archive on github.com', { status: 403 });
    }

    // gist.github.com/<user>/<id>/raw/... -> 转成 gist.githubusercontent.com
    // 这样 Surge 那边只用处理 gist.githubusercontent.com 也可以, 这里做个兼容
    if (target.hostname === 'gist.github.com') {
      target.hostname = 'gist.githubusercontent.com';
    }

    // 缓存: raw 文件变化少, 缓 1 小时; gist 可能随时改, 只缓 5 分钟
    const isGist = target.hostname === 'gist.githubusercontent.com';
    const cacheTtl = isGist ? 300 : 3600;

    const cache = caches.default;
    const cacheKey = new Request(target.toString(), request);
    let response = await cache.match(cacheKey);
    if (response) {
      const hit = new Response(response.body, response);
      hit.headers.set('x-cache', 'HIT');
      hit.headers.set('x-proxy', 'gh-cdn-worker');
      return hit;
    }

    const upstream = await fetch(target.toString(), {
      method: request.method,
      headers: {
        'User-Agent': 'gh-cdn-worker',
        Accept: request.headers.get('Accept') || '*/*',
        // 透传 Range, 支持断点续传 / 大文件分片
        ...(request.headers.get('Range') ? { Range: request.headers.get('Range') } : {}),
      },
      redirect: 'follow',
      cf: { cacheTtl, cacheEverything: true },
    });

    // 上游 404 / 403 等原样透传, 不伪装成成功
    const headers = new Headers();
    for (const name of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified', 'content-disposition']) {
      const v = upstream.headers.get(name);
      if (v) headers.set(name, v);
    }
    headers.set('cache-control', isGist ? 'public, max-age=300' : 'public, max-age=3600');
    headers.set('x-cache', 'MISS');
    headers.set('x-proxy', 'gh-cdn-worker');
    // 不把上游的 set-cookie / CSP 带回来, 避免污染缓存和浏览器行为
    // 注意: 这里刻意不透传 set-cookie

    response = new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });

    // 只缓存成功的 GET 响应
    if (request.method === 'GET' && upstream.status === 200) {
      ctx.waitUntil(cache.put(cacheKey, response.clone()));
    }
    return response;
  },
};
