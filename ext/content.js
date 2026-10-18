(() => {
  if (window.__iqiyiViExt) return;
  window.__iqiyiViExt = true;

  const D = {
    首页: "Trang chủ",
    关注: "Theo dõi",
    短视频: "Video ngắn",
    短剧: "Phim ngắn",
    会员中心: "VIP",
    电视剧: "Phim bộ",
    电影: "Phim",
    动漫: "Anime",
    综艺: "Variety",
    少儿: "Thiếu nhi",
    云影院: "Rạp mây",
    漫剧: "Phim manga",
    纪录片: "Tài liệu",
    知识: "Kiến thức",
    体育: "Thể thao",
    直播: "Live",
    全部频道: "Mọi kênh",
    搜索: "Tìm kiếm",
    开通会员: "Mở VIP",
    开通VIP: "Mở VIP",
    消息: "Tin nhắn",
    历史: "Lịch sử",
    登录: "Đăng nhập",
    注册: "Đăng ký",
    退出登录: "Đăng xuất",
    正在热播: "Đang hot",
    推荐: "Đề xuất",
    最热: "Hot nhất",
    最新: "Mới nhất",
    免费: "Miễn phí",
    广告: "Quảng cáo",
    筛选: "Lọc",
    播放: "Phát",
    收藏: "Yêu thích",
    更多: "Thêm",
    查看更多: "Xem thêm",
    立即观看: "Xem ngay",
    会员: "VIP",
    稍后再看: "Xem sau",
    预约: "Đặt lịch",
    已预约: "Đã đặt",
    排行榜: "Xếp hạng",
    频道: "Kênh",
    片库: "Kho phim",
    设置: "Cài đặt",
    帮助: "Trợ giúp",
    反馈: "Phản hồi",
    下载: "Tải",
    我的下载: "Tải của tôi",
    观看历史: "Đã xem",
    个人中心: "Tài khoản",
    我的: "Của tôi",
    热播榜: "Bảng hot",
    热搜榜: "Tìm kiếm hot",
    猜你喜欢: "Gợi ý cho bạn",
    相关推荐: "Liên quan",
    正在播放: "Đang phát",
    下一集: "Tập sau",
    上一集: "Tập trước",
    全屏: "Toàn màn",
    倍速: "Tốc độ",
    清晰度: "Độ nét",
    字幕: "Phụ đề",
    弹幕: "Danmaku",
    分享: "Chia sẻ",
    投屏: "Chiếu TV",
    关闭: "Đóng",
    取消: "Hủy",
    确定: "OK",
    确认: "Xác nhận",
    重试: "Thử lại",
    刷新: "Tải lại",
    加载中: "Đang tải",
    "加载中...": "Đang tải...",
    正在加载: "Đang tải",
    综合: "Tổng hợp",
    用户: "Người dùng",
    播放量: "Lượt xem",
    完结: "Hết",
    连载: "Đang chiếu",
    独播: "Độc quyền",
    自制: "Tự sản xuất",
    会员免费: "VIP miễn phí",
    限免: "Free tạm",
    学习时刻: "Học tập",
    网络错误: "Lỗi mạng",
    请稍后重试: "Thử lại sau",
    暂无内容: "Chưa có nội dung",
    暂无数据: "Chưa có dữ liệu",
    没有更多了: "Hết rồi",
    全部: "Tất cả",
    高清: "HD",
    超清: "Siêu nét",
    蓝光: "Blu-ray",
    流畅: "Mượt",
    自动: "Tự động",
    原画: "Gốc",
    跳过片头片尾: "Bỏ intro/outro",
    开通黄金VIP: "Mở VIP vàng",
    以非会员观看: "Xem không VIP",
    试看已结束: "Hết xem thử",
    观看完整版: "Xem bản đầy đủ",
    请登录后观看: "Đăng nhập để xem",
    青少年模式: "Chế độ trẻ em",
    继续播放: "Xem tiếp",
    重新播放: "Phát lại",
    播放记录: "Lịch sử xem",
    清空历史: "Xóa lịch sử",
    今天: "Hôm nay",
    昨天: "Hôm qua",
    更早: "Cũ hơn",
    刚刚: "Vừa xong",
    简介: "Tóm tắt",
    详情: "Chi tiết",
    演职员: "Diễn viên",
    评论: "Bình luận",
    相关: "Liên quan",
    正片: "Phim chính",
    预告: "Trailer",
    花絮: "Hậu trường",
    更新至: "Cập nhật tới",
    不感兴趣: "Không quan tâm",
    举报: "Báo cáo",
    点赞: "Thích",
    已关注: "Đã theo dõi",
    取消关注: "Bỏ theo dõi",
    系统消息: "Tin hệ thống",
    全部已读: "Đọc hết",
    热门搜索: "Tìm hot",
    历史搜索: "Đã tìm",
    猜你想搜: "Gợi ý tìm",
    综合: "Tổng hợp",
    用户: "Người dùng",
    播放量: "Lượt xem",
    更新: "Cập nhật",
    完结: "Hết",
    连载: "Đang chiếu",
    独播: "Độc quyền",
    自制: "Tự sản xuất",
    会员免费: "VIP miễn phí",
    用券: "Dùng vé",
    付费: "Trả phí",
    限免: "Free tạm",
    学习时刻: "Học tập",
    筛选: "Lọc",
    搜索: "Tìm kiếm"
  };

  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "NOSCRIPT", "CODE", "SVG"]);

  function translate(s) {
    if (!s) return s;
    const t = s.trim();
    return D[t] ? s.replace(t, D[t]) : s;
  }

  function walk(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      const n = translate(node.nodeValue);
      if (n !== node.nodeValue) node.nodeValue = n;
      return;
    }
    if (node.nodeType !== 1 || SKIP.has(node.tagName)) return;
    if (node.shadowRoot) walk(node.shadowRoot);
    if (node.tagName === "HTML" && node.getAttribute("lang") === "zh") node.setAttribute("lang", "vi");
    for (const a of ["title", "placeholder", "aria-label", "alt"]) {
      const v = node.getAttribute && node.getAttribute(a);
      if (!v) continue;
      const n = translate(v);
      if (n !== v) node.setAttribute(a, n);
    }
    if (node.tagName === "META" && /^(description|keywords)$/i.test(node.getAttribute("name") || "")) {
      const v = node.getAttribute("content");
      const n = translate(v);
      if (n !== v) node.setAttribute("content", n);
    }
    for (const c of node.childNodes) walk(c);
  }

  function run() {
    walk(document.documentElement || document.body);
  }

  run();
  setInterval(run, 800);
  const obs = new MutationObserver(() => {
    if (run._t) cancelAnimationFrame(run._t);
    run._t = requestAnimationFrame(run);
  });
  obs.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true
  });
})();
