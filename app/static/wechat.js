(function () {
  const params = new URLSearchParams(window.location.search);
  const isWeChat = /MicroMessenger/i.test(window.navigator.userAgent);

  const badge = document.getElementById("wechat-badge");
  const sceneValue = document.getElementById("scene-value");
  const openidValue = document.getElementById("openid-value");
  const nicknameValue = document.getElementById("nickname-value");
  const openChatLink = document.getElementById("open-chat-link");

  const scene = params.get("scene") || params.get("from") || "";
  const openid = params.get("openid") || params.get("openId") || "";
  const nickname = params.get("nickname") || params.get("name") || "";
  const redirect = params.get("redirect") || "/chat";

  badge.textContent = isWeChat ? "微信内打开" : "非微信环境";
  badge.classList.add(isWeChat ? "ok" : "warn");

  sceneValue.textContent = scene || "未提供";
  openidValue.textContent = openid || "未提供";
  nicknameValue.textContent = nickname || "未提供";

  const chatUrl = new URL(redirect, window.location.origin);
  for (const [key, value] of params.entries()) {
    if (value) {
      chatUrl.searchParams.set(key, value);
    }
  }
  openChatLink.href = chatUrl.toString();
})();
