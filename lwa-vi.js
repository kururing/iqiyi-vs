/* iqiyi-vi */
(function () {
  var ENGINE_VERSION = 163;
  if (window.__iqiyiVi && window.__iqiyiViVersion === ENGINE_VERSION) {
    if (window.__iqiyiViReload) window.__iqiyiViReload();
    return;
  }
  if (window.__iqiyiViStop) window.__iqiyiViStop();
  var oldStyle = document.getElementById("iqiyi-vi-css");
  if (oldStyle) oldStyle.remove();
  var IQCOM_METADATA_CACHE = new Map();
  var IQCOM_METADATA_WAITERS = new WeakMap();
  var IQCOM_METADATA_QUEUE = [];
  var IQCOM_METADATA_ACTIVE = 0;
  var IQCOM_METADATA_STOPPED = false;
  var IQCOM_METADATA_CONTROLLERS = new Set();
  var IQCOM_PENDING_LABELS = new Set();
  var TEXT_CACHE = new Map();
  var SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, CODE: 1 };
  var FIXED_UI_TARGETS = [
    "#btn_gameBtn", "#clientBtn", "#btn_msgBellBtn", "#btn_historyBtn", "#btn_uploadBtn",
    "#btn_vipBtnB", "#btn_vipBtnS", "#pwaBtn", "#searchinput", "#userCenterSpan",
    '[data-ai-entity="弹幕切换按钮,弹幕开关"]', '[data-ai-entity="弹幕设置按钮"]',
    '[data-ai-entity="弹幕输入框文本输入框"]', '[class*="side_item"]',
    '[class*="cardMemos_channelmark1__"]', '[class*="cardMemos_channelmark2__"]',
    '[class*="cardMemos_channelmark3__"]', '[class*="cardMemos_channelmark4__"]',
    'img[src*="9013485acf0c4e07a2500429869d44f4"]',
    'img[src*="5a2c3f02c5b54771b1047a27cc1f0447"]',
    'img[src*="0b3bd1c78a4b4368b4e2da2fb206b5c8"]',
    'img[src*="ac0bbaca7ffb4528a3a210b4078afbdf"]',
    'img[src*="308107f863864cd8b364bc428f50f4ec"]',
    'img[src*="c4de74820c254b39ae0d692eef59f3a8"]',
    'img[src*="0db0e14b9886439098aa3cadf1b817ab"]',
    'img[src*="5205828ffa8f4fe3aef4e7b2c005148a"]',
    'img[src*="f660fb9c2f57476fbe234f397fd21e37"]'
  ].join(",");
  var FIXED_COPY = {
    "演员": "Diễn viên ",
    "正片": "Tập chính",
    "短片": "Phim ngắn",
    "专访": "Phỏng vấn",
    "加更礼": "Quà mở tập",
    "限免": "Miễn phí có hạn",
    "预告": "Xem trước",
    "花絮": "Hậu trường",
    "选集": "Chọn tập",
    "选集列表": "Danh sách tập",
    "综艺": "Giải trí",
    "云影院": "Rạp trực tuyến",
    "即将上线": "Sắp chiếu",
    "预约": "Đặt nhắc",
    "已预约": "Đã đặt nhắc",
    "会员": "VIP",
    "展开": "Mở rộng",
    "收起": "Thu gọn",
    "更多": "Xem thêm",
    "播放": "Phát",
    "暂停": "Tạm dừng",
    "全屏": "Toàn màn hình",
    "退出全屏": "Thoát toàn màn hình",
    "倍速": "Tốc độ",
    "清晰度": "Chất lượng",
    "弹幕": "Bình luận chạy",
    "字幕": "Phụ đề",
    "简体中文": "Tiếng Trung giản thể",
    "字幕大小": "Cỡ chữ phụ đề",
    "大": "Lớn",
    "特大": "Rất lớn",
    "字幕背景": "Nền phụ đề",
    "开启后，字幕将增加深色背景，浅色画面下更加清晰": "Bật để thêm nền tối cho phụ đề, giúp dễ đọc hơn trên nền sáng.",
    "使用字体：HarmonyOS_Sans_SC_Regular": "Phông chữ: HarmonyOS_Sans_SC_Regular",
    "设置": "Cài đặt",
    "正在看：": "Đang xem:",
    "刷新页面": "Làm mới trang",
    "关注": "Theo dõi",
    "互动": "Tương tác",
    "看影剧": "Xem phim",
    "花积分": "Dùng điểm",
    "换会员": "Đổi VIP",
    "买周边": "Mua quà lưu niệm",
    "会员特惠，新人专享": "Ưu đãi VIP dành cho khách mới",
    "会员尊享4大特权，立即解锁": "Mở ngay 4 nhóm quyền lợi VIP",
    "无法享受免费看、抢先看特权": "Chưa có quyền xem miễn phí và xem sớm",
    "内容特权": "Quyền lợi nội dung",
    "观影特权": "Quyền lợi xem phim",
    "福利特权": "Ưu đãi hội viên",
    "等级特权": "Quyền lợi theo hạng",
    "个人标准会员": "Hội viên cá nhân tiêu chuẩn",
    "电视也能看": "Xem được cả trên TV",
    "加更礼免费看": "Xem miễn phí nội dung mở tập",
    "手机/平板/电脑": "Điện thoại / máy tính bảng / máy tính",
    "双11抢先购": "Ưu đãi sớm 11.11",
    "摇一摇": "Lắc nhận quà",
    "送亲友VIP": "Tặng VIP cho người thân",
    "师生特惠": "Ưu đãi giáo viên, học sinh",
    "联名会员": "Gói hội viên kết hợp",
    "全部联名": "Tất cả gói kết hợp",
    "AI豆换会员": "Đổi đậu AI lấy VIP",
    "最高可换年卡": "Có thể đổi tới gói năm",
    "积分兑会员": "Đổi điểm lấy VIP",
    "随心兑": "Tùy chọn đổi quà",
    "送6个月会员": "Tặng 6 tháng VIP",
    "新装宽带": "Lắp mạng mới",
    "会员+15G": "VIP + 15 GB",
    "首月1分钱": "Tháng đầu 0,01 tệ",
    "VIP+唯品会会员": "VIP + hội viên Vipshop",
    "VIP+百度文库会员": "VIP + Baidu Wenku",
    "VIP+百度网盘会员": "VIP + Baidu Netdisk",
    "VIP+喜马拉雅会员": "VIP + Ximalaya",
    "特惠开会员": "Ưu đãi đăng ký VIP",
    "拼团特惠": "Ưu đãi mua nhóm",
    "邀好友得会员": "Mời bạn nhận VIP",
    "送会员卡": "Tặng thẻ VIP",
    "个人、企业可定制": "Tùy chỉnh cho cá nhân và doanh nghiệp",
    "会员积分换好礼": "Đổi điểm VIP lấy quà",
    "开通会员得积分": "Đăng ký VIP nhận điểm",
    "9.9元享指定饮品3选1": "9,9 tệ: chọn 1 trong 3 đồ uống",
    "美团外卖49元券包": "Gói mã Meituan giao đồ ăn trị giá 49 tệ",
    "京东外卖20-12优惠券": "Mã JD giao đồ ăn: giảm 12 tệ cho đơn 20 tệ",
    "洁柔Lotion保湿纸5包 8元券": "Mã giảm 8 tệ cho 5 gói khăn giấy C&S Lotion",
    "小酥肉0元券": "Mã nhận thịt chiên giòn miễn phí",
    "15.9两件套": "Bộ 2 món giá 15,9 tệ",
    "29.9元双堡": "2 bánh burger giá 29,9 tệ",
    "加更礼观影券": "Vé xem nội dung mở tập",
    "49元美食券包": "Gói mã ăn uống trị giá 49 tệ",
    "39元美食券包": "Gói mã ăn uống trị giá 39 tệ",
    "美团餐饮券包": "Gói mã ăn uống Meituan",
    "百度打车券包": "Gói mã đặt xe Baidu",
    "滴滴代驾券包": "Gói mã tài xế lái hộ DiDi",
    "青桔电单车券包": "Gói mã xe điện Qingju",
    "高德代驾券包": "Gói mã tài xế lái hộ Amap",
    "京东快递券": "Mã chuyển phát JD",
    "门店免费贴膜券": "Mã dán màn hình miễn phí tại cửa hàng",
    "玩乐活动92折": "Giảm 8% cho hoạt động vui chơi",
    "租车95折": "Thuê xe giảm 5%",
    "接送机站88折": "Đưa đón sân bay, nhà ga giảm 12%",
    "携程折扣券": "Mã giảm giá Trip.com",
    "携程机票立减券": "Mã giảm vé máy bay Trip.com",
    "景点门票95折": "Vé tham quan giảm 5%",
    "会员等级特权": "Quyền lợi theo cấp VIP",
    "尊享装扮": "Trang trí độc quyền",
    "去查看": "Xem ngay",
    "生日礼": "Quà sinh nhật",
    "请填写生日日期": "Vui lòng nhập ngày sinh",
    "领黄金会员": "Nhận VIP vàng",
    "专属弹幕": "Bình luận chạy độc quyền",
    "角色/投票/表情": "Nhân vật / bình chọn / biểu cảm",
    "会员热播榜": "Bảng xếp hạng phim VIP",
    "综艺榜": "BXH giải trí",
    "动漫榜": "BXH anime",
    "电视剧榜": "BXH phim bộ",
    "电影榜": "BXH điện ảnh",
    "总榜": "BXH tổng",
    "剧集榜": "BXH phim bộ",
    "去参与": "Tham gia",
    "每日签到即可参与抽奖领月卡": "Điểm danh hằng ngày để bốc thăm nhận VIP tháng",
    "使用爱奇艺Windows客户端": "Dùng ứng dụng iQIYI cho Windows",
    "享更佳视听体验": "Tận hưởng hình ảnh và âm thanh tốt hơn",
    "4K超清视频": "Video 4K sắc nét",
    "杜比音效": "Âm thanh Dolby",
    "离线下载视频": "Tải video để xem ngoại tuyến",
    "无需下载安装，不占电脑空间": "Không cần cài đặt, không chiếm dung lượng máy",
    "暂时还没有收到消息噢": "Bạn chưa có tin nhắn",
    "发布作品": "Đăng tác phẩm",
    "作品管理": "Quản lý tác phẩm",
    "我的空间": "Trang cá nhân",
    "立即购买": "Mua ngay",
    "会员限时大促": "Ưu đãi VIP có thời hạn",
    "进入个人中心": "Vào trang cá nhân",
    "锁定": "Đã khóa",
    "立即预约": "Đặt nhắc ngay",
    "今日上线": "Phát hành hôm nay",
    "明日上线": "Phát hành ngày mai",
    "返回顶部": "Về đầu trang",
    "传奇游戏库": "Kho game Truyền Kỳ",
    "信息网络传播视听节目许可证": "Giấy phép phát nội dung nghe nhìn trực tuyến",
    "营业执照": "Giấy phép kinh doanh",
    "都市生活": "Đời sống đô thị",
    "工业题材": "Đề tài công nghiệp",
    "历史革命": "Lịch sử cách mạng",
    "领袖人物": "Nhân vật lãnh đạo",
    "最新": "Mới nhất",
    "最热": "Đang hot",
    "推荐": "Đề xuất",
    "全部": "Tất cả",
    "地区": "Khu vực",
    "类型": "Thể loại",
    "年份": "Năm",
    "排序": "Sắp xếp",
    "综合排序": "Tổng hợp",
    "最多播放": "Lượt xem nhiều nhất",
    "最近更新": "Cập nhật gần nhất",
    "评分最高": "Điểm cao nhất",
    "中国大陆": "Trung Quốc đại lục",
    "中国香港": "Hồng Kông",
    "中国台湾": "Đài Loan",
    "韩国": "Hàn Quốc",
    "日本": "Nhật Bản",
    "美国": "Mỹ",
    "泰国": "Thái Lan",
    "其他": "Khác",
    "古装": "Cổ trang",
    "爱情": "Tình cảm",
    "悬疑": "Bí ẩn",
    "犯罪": "Tội phạm",
    "喜剧": "Hài",
    "动作": "Hành động",
    "科幻": "Khoa học viễn tưởng",
    "奇幻": "Kỳ ảo",
    "武侠": "Võ hiệp",
    "仙侠": "Tiên hiệp",
    "家庭": "Gia đình",
    "青春": "Thanh xuân",
    "战争": "Chiến tranh",
    "剧情": "Chính kịch",
    "历史": "Lịch sử",
    "冒险": "Phiêu lưu",
    "惊悚": "Giật gân",
    "恐怖": "Kinh dị",
    "播放设置": "Cài đặt phát",
    "画面比例": "Tỷ lệ khung hình",
    "自动连播": "Tự phát tập tiếp",
    "跳过片头片尾": "Bỏ qua đầu và cuối phim",
    "播放列表": "Danh sách phát",
    "剧集列表": "Danh sách tập",
    "精彩片段": "Đoạn phim nổi bật",
    "相关推荐": "Gợi ý liên quan",
    "剧情简介": "Tóm tắt nội dung",
    "演职员": "Diễn viên và ê-kíp",
    "导演": "Đạo diễn",
    "主演": "Diễn viên chính",
    "分享": "Chia sẻ",
    "收藏": "Lưu",
    "已收藏": "Đã lưu",
    "追剧": "Theo dõi phim",
    "已追剧": "Đã theo dõi",
    "举报": "Báo cáo",
    "登录": "Đăng nhập",
    "立即登录": "Đăng nhập ngay",
    "扫码登录": "Quét mã đăng nhập",
    "账号登录": "Đăng nhập tài khoản",
    "手机号": "Số điện thoại",
    "验证码": "Mã xác minh",
    "获取验证码": "Lấy mã xác minh",
    "下载": "Tải xuống",
    "立即开通": "Đăng ký ngay",
    "开通会员": "Đăng ký VIP",
    "续费": "Gia hạn",
    "帮助中心": "Trung tâm trợ giúp",
    "网络异常": "Lỗi kết nối mạng",
    "重新加载": "Tải lại",
    "重试": "Thử lại",
    "添加至网页收藏夹": "Thêm vào dấu trang",
    "使用「CTRL+D」快速添加": "Nhấn Ctrl+D để thêm nhanh",
    "免费解锁VIP，5000+影剧漫等你来看！": "Mở VIP miễn phí, xem hơn 5.000 phim và anime!",
    "古装喜剧": "Hài cổ trang",
    "古装爱情": "Tình cảm cổ trang",
    "古装探案": "Phá án cổ trang",
    "古偶": "Ngôn tình cổ trang",
    "偶像爱情": "Tình cảm thần tượng",
    "复仇": "Báo thù",
    "仙侠玄幻": "Tiên hiệp huyền huyễn",
    "轻喜剧": "Hài nhẹ nhàng",
    "头脑博弈": "Đấu trí",
    "成长烦恼": "Trưởng thành",
    "探险寻宝": "Phiêu lưu tìm kho báu",
    "甜虐爱情": "Tình yêu ngọt ngào và ngang trái",
    "民国传奇": "Truyền kỳ thời Dân quốc",
    "江湖恩怨": "Ân oán giang hồ",
    "金鹰奖": "Giải Kim Ưng",
    "白玉兰奖": "Giải Bạch Ngọc Lan",
    "佳片殿堂": "Tác phẩm kinh điển",
    "古装剧": "Phim cổ trang",
    "奇幻剧": "Phim kỳ ảo",
    "热播": "Đang hot",
    "电视剧热播": "Phim bộ đang hot",
    "关闭": "Đóng",
    "取消": "Hủy",
    "确定": "Xác nhận",
    "确 定": "Xác nhận",
    "取 消": "Hủy",
    "确认": "Xác nhận",
    "提示": "Thông báo",
    "返回": "Quay lại",
    "完成": "Xong",
    "退出": "Thoát",
    "退出应用": "Thoát ứng dụng",
    "最小化": "Thu nhỏ",
    "最大化": "Phóng to",
    "还原窗口": "Khôi phục cửa sổ",
    "关于": "Giới thiệu",
    "恢复默认": "Khôi phục mặc định",
    "恢复默认设置": "Khôi phục cài đặt mặc định",
    "检查更新": "Kiểm tra cập nhật",
    "在线升级": "Cập nhật trực tuyến",
    "意见反馈": "Góp ý",
    "帮助反馈": "Trợ giúp và phản hồi",
    "帮助": "Trợ giúp",
    "赚钱": "Kiếm tiền",
    "签到赚金币，可提现": "Điểm danh nhận xu, có thể rút tiền",
    "正在热播": "Đang hot",
    "猜你喜欢": "Có thể bạn thích",
    "今日推荐": "Gợi ý hôm nay",
    "换一换": "Đổi gợi ý",
    "更多精彩": "Xem thêm nội dung",
    "全部内容": "Tất cả nội dung",
    "公司介绍": "Giới thiệu công ty",
    "专业内容合作": "Hợp tác nội dung chuyên nghiệp",
    "爱奇艺号": "Kênh iQIYI",
    "爱奇艺纳逗Pro": "iQIYI NaDou Pro",
    "创作者关系及服务": "Quan hệ và dịch vụ nhà sáng tạo",
    "会员/广告业务合作": "Hợp tác hội viên và quảng cáo",
    "体验业务合作": "Hợp tác sản phẩm trải nghiệm",
    "用户协议": "Điều khoản sử dụng",
    "隐私政策": "Chính sách riêng tư",
    "广告": "Quảng cáo",
    "字幕设置": "Cài đặt phụ đề",
    "音频设置": "Cài đặt âm thanh",
    "输出设备": "Thiết bị đầu ra",
    "画面调节": "Điều chỉnh hình ảnh",
    "声音": "Âm thanh",
    "静音": "Tắt tiếng",
    "取消静音": "Bật tiếng",
    "音量": "Âm lượng",
    "原画": "Chất lượng gốc",
    "超清": "Siêu nét",
    "高清": "HD",
    "标清": "Tiêu chuẩn",
    "流畅": "Mượt",
    "自动": "Tự động",
    "开启": "Bật",
    "关闭弹幕": "Tắt bình luận chạy",
    "开启弹幕": "Bật bình luận chạy",
    "透明度": "Độ trong suốt",
    "字体大小": "Cỡ chữ",
    "显示区域": "Vùng hiển thị",
    "屏蔽词": "Từ chặn",
    "快捷键": "Phím tắt",
    "快捷键设置": "Cài đặt phím tắt",
    "播放顺序": "Thứ tự phát",
    "顺序播放": "Phát lần lượt",
    "顺序循环": "Lặp danh sách",
    "单个播放": "Phát một lần",
    "单个循环": "Lặp một tập",
    "随机播放": "Phát ngẫu nhiên",
    "下一集": "Tập tiếp",
    "上一集": "Tập trước",
    "重播": "Phát lại",
    "播放失败": "Không phát được",
    "加载中": "Đang tải",
    "正在加载...": "Đang tải…",
    "请稍候...": "Vui lòng chờ…",
    "点击重试": "Nhấn để thử lại",
    "点击刷新": "Nhấn để tải lại",
    "网络连接失败": "Kết nối mạng thất bại",
    "打开文件": "Mở tệp",
    "打开文件夹": "Mở thư mục",
    "更改目录": "Đổi thư mục",
    "下载管理": "Quản lý tải xuống",
    "下载完成": "Đã tải xong",
    "正在下载": "Đang tải xuống",
    "全部暂停": "Tạm dừng tất cả",
    "全部开始": "Bắt đầu tất cả",
    "删除": "Xóa",
    "清空": "Xóa hết",
    "编辑": "Chỉnh sửa",
    "保存": "Lưu",
    "保存成功": "Đã lưu",
    "操作失败": "Thao tác thất bại",
    "播放记录": "Lịch sử xem",
    "清空记录": "Xóa lịch sử",
    "我的收藏": "Nội dung đã lưu",
    "消息中心": "Trung tâm tin nhắn",
    "暂无消息": "Chưa có tin nhắn",
    "暂无内容": "Chưa có nội dung",
    "退出登录": "Đăng xuất",
    "切换账号": "Đổi tài khoản",
    "账号设置": "Cài đặt tài khoản",
    "搜索历史": "Lịch sử tìm kiếm",
    "热门搜索": "Tìm kiếm phổ biến",
    "搜索结果": "Kết quả tìm kiếm",
    "没有找到相关结果": "Không tìm thấy kết quả phù hợp",
    "清除历史": "Xóa lịch sử tìm kiếm",
    "登录后查看": "Đăng nhập để xem",
    "评论": "Bình luận",
    "回复": "Trả lời",
    "发表评论": "Viết bình luận",
    "发送": "Gửi",
    "展开更多": "Xem thêm",
    "收起全部": "Thu gọn tất cả",
    "相关视频": "Video liên quan",
    "简介": "Giới thiệu",
    "选集播放": "Chọn tập để xem",
    "正片列表": "Danh sách tập chính",
    "仅看正片": "Chỉ xem tập chính",
    "小窗播放": "Phát cửa sổ nhỏ",
    "画中画": "Hình trong hình",
    "投屏": "Truyền lên TV",
    "投屏设置": "Cài đặt truyền màn hình",
    "反馈与修复": "Phản hồi và sửa lỗi",
    "立即修复": "Sửa ngay",
    "不再提示": "Không nhắc lại",
    "下次再说": "Để lần sau",
    "稍后提醒": "Nhắc sau",
    "继续播放": "Tiếp tục phát",
    "重新播放": "Phát lại",
    "已看完": "Đã xem hết",
    "跳过": "Bỏ qua",
    "跳过片头": "Bỏ qua phần đầu",
    "跳过片尾": "Bỏ qua phần cuối",
    "豆瓣高分": "Điểm Douban cao",
    "言情": "Ngôn tình",
    "搞笑": "Hài hước",
    "偶像": "Thần tượng",
    "励志": "Truyền cảm hứng",
    "律政题材": "Đề tài pháp luật",
    "创业": "Khởi nghiệp",
    "请更新显卡驱动": "Hãy cập nhật driver card đồ họa",
    "非常抱歉，页面加载出错，请": "Trang lỗi, vui lòng",
    "极简模式": "Chế độ tối giản",
    "播放本地文件": "Phát tệp máy",
    "添加爱奇艺到桌面": "Ghim iQIYI ra desktop",
    "在线客服": "Hỗ trợ trực tuyến",
    "用户协议与隐私保护": "Điều khoản và quyền riêng tư",
    "同意并继续": "Đồng ý và tiếp tục",
    "不同意": "Không đồng ý",
    "正在加载,请稍候...": "Đang tải, chờ chút...",
    "哎呀,数据跑去火星啦,检查网络试试~": "Lỗi dữ liệu, hãy kiểm tra mạng.",
    "热搜榜": "Bảng tìm kiếm nổi bật",
    "每月6元": "6 tệ/tháng",
    "菜单": "Menu",
    "隐藏爱奇艺": "Ẩn iQIYI",
    "打开爱奇艺": "Mở iQIYI",
    "反馈": "Phản hồi",
    "调试器": "Trình gỡ lỗi",
    "资源管理器": "Trình quản lý tệp",
    "修复页面": "Sửa trang",
    "正在下载...": "Đang tải...",
    "页面加载失败，请重新加载！": "Tải trang lỗi, hãy thử lại!",
    "刷新本页": "Tải lại trang",
    "您的账号在多台设备同时播放视频，存在极高的盗号风险。": "Tài khoản đang phát trên nhiều máy, rủi ro bị chiếm cao.",
    "为保护您的账号安全，请尽快退登其他设备或修改密码。": "Hãy đăng xuất máy khác hoặc đổi mật khẩu.",
    "想继续观看？请关闭其他设备下的视频播放。": "Muốn xem tiếp? Hãy tắt phát trên máy khác.",
    "然后点击": "Rồi bấm",
    "<u><c #009F69>重试</c></u>": "<u><c #009F69>Thử lại</c></u>",
    "如非本人操作，建议您立即修改密码。": "Nếu không phải bạn, hãy đổi mật khẩu ngay.",
    "修改密码": "Đổi mật khẩu",
    "以非会员观看": "Xem không VIP",
    "游戏中心": "Trung tâm game",
    "美女直播": "Livestream",
    "开始游戏": "Chơi",
    "新建下载任务": "Tác vụ tải mới",
    "清晰度：": "Độ nét:",
    "蓝光 ": "Blu-ray ",
    "全选": "Chọn tất cả",
    "下载至：": "Tải vào:",
    "下载你选中的视频，需要": "Tải video đã chọn cần",
    "或": "hoặc",
    "开通VIP": "Mua VIP",
    "你选中了VIP清晰度，需要": "Bạn chọn độ nét VIP, cần",
    "版权保护，下载视频请": "Bản quyền, muốn tải hãy",
    "购买": "Mua",
    "版权保护，暂不支持下载会员加更礼选集": "Do bảo vệ bản quyền, việc tải xuống bộ sưu tập quà tặng thành viên hiện không được hỗ trợ.",
    "你选中了xxxxxxxx，需要": "Bạn đã chọn xxxxxxxx và cần",
    "开通黄金VIP": "Mở VIP vàng",
    "下载目录无效，请更改目录": "Thư mục tải không hợp lệ, hãy đổi",
    "下载(0)": "Tải (0)",
    "登录后下载(0)": "Đăng nhập rồi tải (0)",
    "数据正在加载中......": "Đang tải dữ liệu...",
    "网络加载超时，请": "Hết thời gian mạng, hãy",
    "重新试试": "Thử lại",
    "由于版权限制，视频不允许下载！": "Do hạn chế về bản quyền nên video không được phép tải xuống!",
    "超前解锁剧集需要会员购买后才可下载": "Mở khóa sớm các tập yêu cầu mua tư cách thành viên trước khi tải xuống",
    "蓝光4K": "Blu-ray 4K",
    "已加入下载列表": "Đã thêm vào danh sách tải",
    "可至个人中心-": "Bạn có thể đến trung tâm cá nhân -",
    "我的下载": "Tải của tôi",
    "查看": "Xem",
    "快来观看吧~": "Vào xem ngay",
    "立即观看": "Xem ngay",
    "加入播单稍后看": "Thêm vào xem sau",
    "双击桌面图标可以立即播放哦": "Bấm đúp vào biểu tượng trên màn hình để chơi ngay",
    "我知道了": "Đã hiểu",
    "正在升级，请稍候 1%": "Đang nâng cấp, vui lòng đợi 1%",
    "不在提示": "Không nhắc nữa",
    "糟糕！检测到爱奇艺客户端文件损坏，已完成修复，请重新打开爱奇艺。": "Ôi! Phát hiện tệp iQIYI bị hỏng và đã sửa xong. Hãy mở lại iQIYI.",
    "刚才软件出了点小故障，现已自动修复": "Vừa rồi có một trục trặc trong phần mềm và nó đã được tự động sửa chữa.",
    "捂脸求原谅~": "Hãy che mặt lại và cầu xin sự tha thứ ~",
    "后自动关闭": " rồi tự đóng",
    "是否打开爱奇艺轮播台观看？": "Bạn có muốn mở băng chuyền iQiyi để xem không?",
    "爱奇艺Windows客户端": "Máy khách Windows iQiyi",
    "和爱奇艺共同打造": "Được tạo cùng với iQiyi",
    "Copyright © 2023 爱奇艺 All Rights Reserved": "Copyright © 2023 iQIYI. Bảo lưu mọi quyền",
    "自动修复": "Tự sửa",
    "问题诊断中，请稍候…": "Đang chẩn đoán sự cố, vui lòng đợi...",
    "检测到以下问题，请选择需要修复的内容，然后点击「开始修复」": "Đã phát hiện các vấn đề sau; hãy chọn mục cần sửa rồi bấm «Bắt đầu sửa».",
    "修复卡顿问题": "Khắc phục sự cố lag",
    "修复音量问题": "Sửa lỗi âm lượng",
    "修复DRM播放错误": "Sửa lỗi phát lại DRM",
    "修复播放花屏(仅在播放时出现花屏，可尝试此项修复)": "Sửa lỗi vỡ hình khi phát (chỉ lỗi khi phát, có thể thử cách sửa này).",
    "检测到播放时其他应用程序占用较多资源，请手动关闭其他非必要的程序": "Phát hiện ứng dụng khác đang dùng nhiều tài nguyên khi phát; hãy đóng các ứng dụng không cần thiết.",
    "开始修复": "Bắt đầu sửa",
    "修复完成（重启后生效）~": "Sửa chữa hoàn tất (sẽ có hiệu lực sau khi khởi động lại) ~",
    "未检测到需要修复的问题~": "Không phát hiện thấy vấn đề nào cần khắc phục~",
    "修复中…": "Đang sửa…",
    "正在修复相关问题 请稍等…": "Các vấn đề liên quan đang được khắc phục. Vui lòng chờ...",
    "后台运行": "Chạy nền",
    "历史反馈": "Góp ý cũ",
    "升级客户端": "Cập nhật app",
    "其他问题或建议": "Góp ý khác",
    "请选择具体问题出现的场景": "Chọn tình huống gặp lỗi",
    "您的电脑使用4K码流，可能会出现卡顿、崩溃、花屏等问题": "Xem 4K trên máy này có thể giật, crash hoặc vỡ hình",
    "正在修复": "Đang sửa",
    "修复后仍存在问题？": "Sửa xong vẫn lỗi?",
    "试试上传日志>": "Thử tải nhật ký lên>",
    "请输入手机号、QQ或邮箱（选填）": "Vui lòng nhập số điện thoại di động, QQ hoặc email của bạn (tùy chọn)",
    "立即反馈": "Góp ý ngay",
    "感谢你的反馈!": "Cảm ơn phản hồi!",
    "我们会尽快为你解决问题!": "Chúng tôi sẽ xử lý sớm!",
    "特别提示:": "Lưu ý:",
    "1.为尽快解决问题，爱奇艺客服人员可能会联系你": "1. Nhân viên hỗ trợ có thể liên hệ bạn",
    "<c #999999>2.遇到问题，也可以联系</c><a http://cserver.iqiyi.com/index?e=9><c #23d41e>在线客服</c></a>": "<c #999999>2. Gặp vấn đề, liên hệ </c><a http://cserver.iqiyi.com/index?e=9><c #23d41e>hỗ trợ online</c></a>",
    "继续反馈": "Tiếp tục góp ý",
    "建议更新版本": "Nên cập nhật bản",
    "当前问题可能是未更新到最新版造成的，": "Sự cố hiện tại có thể xảy ra do không cập nhật lên phiên bản mới nhất.",
    "请更新后重试。": "Vui lòng cập nhật và thử lại.",
    "仍要反馈": "Vẫn góp ý",
    "立即更新": "Cập nhật ngay",
    "定时设置": "Hẹn giờ",
    "您选择了定时关机，系统将在": "Nếu bạn chọn tắt máy theo lịch trình, hệ thống sẽ",
    "内关闭": "đóng cửa bên trong",
    "立即关机": "Tắt máy ngay",
    "取消关机": "Hủy tắt máy",
    "反馈与建议": "Phản hồi và đề xuất",
    "我要投诉：": "Tôi muốn khiếu nại:",
    "一直在缓冲，不能播放": "Tiếp tục bị giật và không thể chơi",
    "播放不流畅，卡": "Phát lại không mượt, bị kẹt",
    "图像声音不同步": "Hình ảnh và âm thanh không đồng bộ",
    "影片内容不丰富": "Nội dung video chưa phong phú",
    "频道列表无法展现": "Danh sách kênh không thể hiển thị",
    "软件崩溃无反应": "Phần mềm gặp sự cố và không phản hồi",
    "界面不美观": "Giao diện khó coi",
    "广告问题": "Vấn đề quảng cáo",
    "其它": "Khác",
    "试试": "Thử",
    "一键修复": "Sửa một chạm",
    "，快速解决播放、展示、崩溃相关问题": ", giải quyết nhanh chóng các vấn đề liên quan đến phát, hiển thị, treo máy",
    "意见建议：": "Góp ý:",
    "联系方式：": "Liên hệ:",
    "电话/邮箱/QQ": "Điện thoại/email/QQ",
    "<c #999999>遇到问题，可以联系</c><a http://cserver.iqiyi.com/index?e=9><c #00CC36>在线客服</c></a><c #999999> 或 拨打24小时客服电话：</c><c #00CC36>400-923-7171</c>": "<c #999999>Nếu gặp vấn đề, hãy liên hệ </c><a http://cserver.iqiyi.com/index?e=9><c #00CC36>hỗ trợ online</c></a><c #999999> hoặc gọi CSKH 24 giờ: </c><c #00CC36>400-923-7171</c>",
    "修复": "Sửa",
    "定时关机": "Hẹn giờ tắt máy",
    "重置定时": "Đặt lại hẹn giờ",
    "影片播放完成后关机": "Tắt sau khi phát lại video hoàn tất",
    "离线任务下载完成后关机": "Tắt máy tính sau khi tải tác vụ offline",
    "时": "giờ",
    "分 后关机": "Tắt máy sau",
    "后关机": "tắt máy sau",
    "确 认": "Xác nhận",
    "客户端软件出现异常情况啦!T^T": "Đã xảy ra sự cố bất thường trong phần mềm máy khách! T^T",
    "下载最新版试试哦": "Tải về phiên bản mới nhất và thử nó",
    "下载新版客户端": "Tải bản mới",
    "<c #999999>遇到问题，可以联系</c><a http://cserver.iqiyi.com/index?e=9><c #45b000>在线客服</c></a><c #999999> 或 拨打24小时客服电话：</c><c #45b000><y -15>400-923-7171</c>": "<c #999999>Nếu gặp vấn đề, hãy liên hệ </c><a http://cserver.iqiyi.com/index?e=9><c #45b000>hỗ trợ online</c></a><c #999999> hoặc gọi CSKH 24 giờ: </c><c #45b000><y -15>400-923-7171</c>",
    "开通VIP会员": "Mở VIP",
    "享2-3个并行下载特权": "Tận hưởng đặc quyền tải xuống song song 2-3",
    "会员尊享": "Đặc quyền VIP",
    "下载加速": "Tăng tốc tải",
    "并行下载": "tải xuống song song",
    "边下边播": "Chơi trong khi tải xuống",
    "预约下载": "Cuộc hẹn để tải về",
    "已是会员？": "Đã là VIP?",
    "立即登录>": "Đăng nhập ngay >",
    "限时特惠": "Ưu đãi có hạn",
    "升级至V5": "Nâng lên V5",
    "可解锁4-5个并行下载特权": "Mở khóa 4-5 đặc quyền tải xuống song song",
    "升级秘籍": "Nâng cấp gian lận",
    "每日观影满60分钟成长值最高+10点": "Sau khi xem phim 60 phút mỗi ngày, giá trị tăng trưởng tối đa là +10 điểm",
    "知道了": "Đã hiểu",
    "爱奇艺": "iQIYI",
    "精彩内容随时看": "Xem nội dung thú vị bất cứ lúc nào",
    "打开爱奇艺客户端，畅享更多精彩": "Mở ứng dụng khách iQiyi và tận hưởng những giây phút thú vị hơn",
    "立刻播放": "Chơi ngay",
    "不再弹出": "Không hiện lại",
    "正在拼命加载中，请稍候......": "Đang tải khó, vui lòng đợi...",
    "不小心数据加载失败了,请": "Vui lòng vô tình tải dữ liệu không thành công",
    "直接离开": "Rời luôn",
    "去玩游戏": "đi chơi game",
    "视频看累了吗？再来玩会儿游戏吧！": "Bạn chán xem video? Hãy chơi lại vài trò chơi nhé!",
    "以后不再提示": "Đừng nhắc lại trong tương lai",
    "玩游戏领VIP": "Chơi game nhận VIP",
    "玩游戏": "Chơi game",
    "领VIP": "Nhận VIP",
    "已完成": "Hoàn tất",
    "每天玩5分钟，集满15天可兑换月卡": "Chơi 5 phút mỗi ngày và đổi thẻ tháng sau 15 ngày.",
    "查看更多": "Xem thêm",
    "领取失败,请稍后重试": "Không thu thập được, vui lòng thử lại sau",
    "查看全部消息": "Xem mọi tin",
    "查看全部未读消息": "Xem tin chưa đọc",
    "经典版登录": "Đăng nhập bản cũ",
    "<c #666666>打开</c><c #0ccc4c>爱奇艺手机APP</c>": "<c #666666>Mở </c><c #0ccc4c>app iQIYI điện thoại</c>",
    "扫描二维码登录": "Quét QR để đăng nhập",
    "二维码已失效": "Mã QR hết hạn",
    "扫码成功": "Quét mã thành công",
    "请在手机上确认[授权登录]": "Xác nhận [cho phép đăng nhập] trên điện thoại",
    "登录成功": "Đăng nhập thành công",
    "展开列表栏": "Mở cột danh sách",
    "艺起奔跑吧": "Hãy chạy vì nghệ thuật",
    "歌手再征途": "Ca sĩ bước vào một hành trình khác",
    "电视剧": "Phim bộ",
    "电影": "Phim",
    "儿童": "Thiếu nhi",
    "动漫": "Anime",
    "游戏": "Game",
    "纪录片": "Tài liệu",
    "会员中心": "Trung tâm VIP",
    "体育": "Thể thao",
    "知识": "Kiến thức",
    "直播": "Livestream",
    "随刻热点": "Tin nóng",
    "娱乐": "Giải trí",
    "资讯": "Tin tức",
    "音乐": "Nhạc",
    "汽车": "Ô tô",
    "军事": "Quân sự",
    "母婴": "Mẹ và bé",
    "健康": "Sức khỏe",
    "全网榜单": "Bảng toàn mạng",
    "搜索": "Tìm",
    "我的": "Của tôi",
    "加载异常，请点击返回首页！": "Đang tải ngoại lệ, vui lòng bấm vào để trở về trang chủ!",
    "爱奇艺PC客户端已准备就绪": "Máy khách iQiyi PC đã sẵn sàng",
    "打开": "Mở",
    "您的系统缺少微软": "Hệ thống của bạn đang thiếu Microsoft",
    "WebView2组件": "Thành phần WebView2",
    "，正在为您下载安装，请稍候...": ", đang tải và cài đặt cho bạn, bạn vui lòng đợi nhé...",
    "爱奇艺PC客户端依赖该组件，安装完成后即可正常使用，且仅需安装一次": "Ứng dụng iQIYI PC cần thành phần này; cài xong có thể dùng bình thường và chỉ cần cài một lần.",
    "正在解压微软": "Giải nén Microsoft",
    "，请稍候...": ", vui lòng chờ...",
    "爱奇艺PC客户端已准备就绪，正在启动中...": "Ứng dụng iQIYI PC đã sẵn sàng, đang khởi động...",
    "跳转爱奇艺网页版": "Chuyển sang phiên bản web iQiyi",
    "手动下载包含完整组件的客户端": "Tải xuống ứng dụng khách theo cách thủ công với các thành phần hoàn chỉnh",
    "复制下载链接": "Sao chép liên kết tải xuống",
    "如需帮助，请加QQ群联系我们，QQ群号：48328857": "Cần trợ giúp? Hãy tham gia nhóm QQ để liên hệ: 48328857",
    "复制QQ群": "Sao chép nhóm QQ",
    "WebView2是微软提供的页面显示组件，爱奇艺PC": "WebView2 là thành phần hiển thị trang của Microsoft, dùng cho iQIYI PC.",
    "客户端内的部分页面需要该组件支持": "Một số trang trong client yêu cầu hỗ trợ từ thành phần này",
    "当前电脑暂未安装，安装后即可正常使用，不会影响": "Máy tính hiện chưa cài đặt; cài xong có thể dùng bình thường, không ảnh hưởng.",
    "您的个人文件和系统设置": "Tệp cá nhân và cài đặt hệ thống",
    "<u>点击此处跳转微软官网下载WebView2组件</u>": "<u>Bấm vào đây để tới trang Microsoft tải thành phần WebView2</u>",
    "不感兴趣": "Không quan tâm",
    "正在加载，请稍候...": "Đang tải, vui lòng đợi...",
    "未能正常连接网络！": "Không thể kết nối mạng đúng cách!",
    "请检查网络连接是否正常，如果连接正常，请关闭重试": "Hãy kiểm tra kết nối mạng; nếu bình thường, hãy đóng rồi thử lại.",
    "关闭广告": "Đóng QC",
    "关闭广告，放大暂停画面": "Đóng quảng cáo để phóng to khung hình khi tạm dừng",
    "主标题": "Tiêu đề",
    "观看至50": "Xem tới 50",
    "还没有观看历史哟~": "Chưa xem lịch sử~",
    "登录后可同步观看历史": "Đăng nhập để đồng bộ lịch sử",
    "描述看点": "Miêu tả những điểm nổi bật",
    "2小时前更新": "Đã cập nhật 2 giờ trước",
    "查看更新 ": "Xem thông tin cập nhật ",
    "主标题多行内容": "Tiêu đề chính nội dung nhiều dòng",
    "今天": "Hôm nay",
    "过滤短视频": "Ẩn video ngắn",
    "观看历史": "Đã xem",
    "查看更多观看历史": "Xem thêm lịch sử",
    "副标题": "Phụ đề",
    "  +订阅": "  +Đăng ký",
    "查更新": "Xem cập nhật",
    "用爱奇艺极简模式一键续播，发现更多精彩内容。可在主界面顶部菜单中开启/关闭本功能": "Dùng chế độ tối giản iQIYI để tiếp tục phát chỉ với một lần bấm và khám phá thêm nội dung hay. Có thể bật/tắt ở menu trên cùng.",
    "一键追剧、快捷搜索、小窗刷视频，就用爱奇艺极简模式": "Theo dõi phim, tìm nhanh và xem video cửa sổ nhỏ với chế độ tối giản iQIYI.",
    "短视频": "Video ngắn",
    "小游戏": "Game nhỏ",
    "新片": "Mới",
    "关闭极简模式：": "Tắt chế độ tối giản:",
    "仅本次关闭": "Chỉ lần này",
    "永久关闭": "Đóng vĩnh viễn",
    "极简模式介绍": "Giới thiệu về chế độ tối giản",
    "极简模式已永久关闭": "Chế độ tối giản đã bị tắt vĩnh viễn",
    "后续可在爱奇艺菜单中重新打开极简模式": "Bạn có thể mở lại chế độ tối giản trong menu iQiyi sau.",
    "提示文本": "Gợi ý",
    "看正片": "Xem phim",
    "请检查网络连接是否正常，如果连接正常": "Hãy kiểm tra mạng. Nếu mạng ổn,",
    "请刷新本页": "hãy tải lại trang",
    "360安全卫士": "Nhân viên bảo vệ 360",
    "轻巧快速免打扰，强力杀毒不卡机": "Nhẹ, nhanh, không gián đoạn, diệt virus mạnh mẽ không lag",
    "安装完成，欢迎来到爱奇艺": "Quá trình cài đặt hoàn tất, chào mừng bạn đến với iQiyi",
    "由于您的系统缺少微软应用组件，正在为您下载中": "Hệ thống thiếu thành phần ứng dụng Microsoft, đang tải xuống...",
    "完成前可能会影响爱奇艺PC客户端启动": "Trước khi hoàn thành, nó có thể ảnh hưởng đến việc khởi động máy khách iQiyi PC",
    "立即进入": "Vào ngay",
    "允许启用开机自动运行 新热内容随时看": "Cho phép kích hoạt hoạt động tự động khi khởi động. Xem nội dung nóng mới bất cứ lúc nào.",
    "设置为默认本地播放器 简约易用不卡顿": "Đặt làm trình phát mặc định, gọn, ít giật",
    "开机自动运行极简模式 一键开播速上手": "Tự động chạy ở chế độ tối giản khi khởi động, chỉ cần một cú nhấp chuột để bắt đầu phát sóng và bắt đầu nhanh chóng",
    "推荐您安装以下软件": "Nên cài các phần mềm sau",
    "搬家成功，是否重启客户端？": "Việc di chuyển đã thành công. Bạn có muốn khởi động lại máy khách không?",
    "立即重启（5s）": "Mở lại ngay (5s)",
    "安装完成": "Cài xong",
    "立即体验": "Dùng ngay",
    "<c #979798>将</c><c #e7e7e8> 爱奇艺PC客户端</c><c #979798>一并添加至桌面快捷方式</c>": "<c #979798>Thêm </c><c #e7e7e8>ứng dụng iQIYI PC</c><c #979798> vào lối tắt trên desktop</c>",
    "自定义设置（推荐）": "Tùy chỉnh (khuyên dùng)",
    "及时获取最新视频（允许开机自启、今日推荐、资讯热点）": "Nhận video mới kịp thời (cho phép tự chạy cùng máy, gợi ý hôm nay và tin nóng).",
    "正在检测新版本，请稍候...": "Đang phát hiện phiên bản mới, vui lòng đợi...",
    "当前已是最新版本": "Đã là bản mới nhất",
    "如果您在使用过程中出现故障或错误，可以点击修复按钮进行修复": "Nếu gặp lỗi trong quá trình sử dụng, hãy bấm nút Sửa để khắc phục.",
    "升级失败，请稍候重试！": "Cập nhật lỗi, thử lại sau!",
    "立即升级": "Cập nhật ngay",
    "下次启动升级": "Bắt đầu nâng cấp vào lần tiếp theo",
    "好的": "Được",
    "正在下载至": "Đang tải xuống",
    "首页": "Trang chủ",
    "爱奇艺短视频": "Video ngắn iQIYI",
    "爱奇艺游戏": "Game iQIYI",
    "会员俱乐部": "Câu lạc bộ VIP",
    "应用": "Ứng dụng",
    "浏览器": "Trình duyệt",
    "爱奇艺轮播台": "Kênh luân phiên iQIYI",
    "奇秀插件": "Plugin Qixiu",
    "爱奇艺文学": "Văn học iQIYI",
    "游戏直播": "Livestream game",
    "漫画": "Truyện tranh",
    "爱奇艺知识": "Kiến thức iQIYI",
    "后退": "Lùi",
    "前进": "Tiến",
    "刷新": "Tải lại",
    "播放器模式": "Chế độ trình phát",
    "网页模式": "Chế độ web",
    "关闭网页": "Đóng trang",
    "上传中…": "Đang tải lên…",
    "正在上传日志 请稍等…": "Đang tải nhật ký lên, vui lòng đợi...",
    "驱动修复": "Sửa driver",
    "修复显卡": "Sửa chữa card đồ họa",
    "修复时可能出现多个弹窗，请选择当前设备驱动进行": "Có thể hiện nhiều cửa sổ, hãy chọn driver máy này",
    "操作。": "để thao tác.",
    "修复声卡": "Sửa chữa card âm thanh",
    "对产品功能或使用体验上有任何问题或建议，欢迎随时": "Nếu có vấn đề hoặc góp ý về chức năng hay trải nghiệm, hãy liên hệ bất cứ lúc nào.",
    "反馈。": "để phản hồi.",
    "其他修复": "Sửa khác",
    "恢复出厂设置": "Khôi phục cài đặt gốc",
    "恢复所有配置成出厂时。": "Khôi phục tất cả các cấu hình về cài đặt gốc.",
    "恢复设置": "Khôi phục cài đặt",
    "清除本地缓存": "Xóa bộ nhớ đệm cục bộ",
    "清除本地缓存的图片、数据等文件。": "Xóa hình ảnh, dữ liệu và các tập tin khác được lưu trong bộ nhớ đệm cục bộ.",
    "清除缓存": "xóa bộ nhớ đệm",
    "hosts清空": "xóa máy chủ",
    "清空错误的hosts设置。": "Xóa cài đặt máy chủ sai.",
    "立即清空": "Xóa ngay bây giờ",
    "播放异常": "Lỗi phát",
    "花屏、闪屏、黑屏、白屏、屏幕抖动": "Màn hình nhấp nháy, màn hình nhấp nháy, màn hình đen, màn hình trắng, màn hình giật hình",
    "请确保显卡驱动为最新。": "Hãy đảm bảo trình điều khiển card đồ họa được cập nhật.",
    "播放卡顿": "Phát lại bị treo",
    "点击立即修复解决卡顿问题。": "Nhấp vào Repair Now để giải quyết vấn đề lag.",
    "无4K码流": "Không có luồng 4K",
    "您的电脑使用4K码流,可能会出现卡顿、崩溃、花屏等": "Máy tính dùng luồng 4K có thể bị giật, crash hoặc vỡ hình.",
    "问题。": "sự cố.",
    "播放无画面": "Không có hình ảnh trong khi phát lại",
    "播放有声音无画面、无播放界面等问题": "Các vấn đề như có âm thanh nhưng không có hình ảnh khi phát lại, không có giao diện phát lại, v.v.",
    "展示异常": "Lỗi hiển thị",
    "页面展示空白": "Hiển thị trang trống",
    "点击立即修复页面空白、内容无法展示的问题。": "Nhấn vào đây để khắc phục ngay tình trạng trang trống không hiển thị được nội dung.",
    "声音异常": "Lỗi âm thanh",
    "无声音或者音量过大。": "Không có âm thanh hoặc âm lượng quá lớn.",
    "开启与关闭：": "Bật / tắt:",
    "开机自动运行": "Chạy cùng Windows",
    "开机自动运行极简模式": "Mở Windows bằng chế độ tối giản",
    "当程序最小化后显示在": "Khi thu nhỏ thì hiện ở",
    "任务栏": "Thanh tác vụ",
    "托盘": "Khay hệ thống",
    "点击关闭按钮时": "Khi bấm nút đóng",
    "最小化到托盘": "Thu nhỏ xuống khay",
    "点击关闭按钮时，极简模式将": "Khi đóng, chế độ tối giản sẽ",
    "保持打开": "Giữ mở",
    "下载管理:": "Quản lý tải:",
    "下载文件存放路径（更改路径将于下次下载时生效）": "Thư mục tải (đổi path áp dụng lần tải sau)",
    "自动下载未完成的任务": "Tự tải tiếp tác vụ dở",
    "所有下载任务完成后自动关机": "Tắt máy khi tải xong hết",
    "创建视频专辑文件夹": "Tạo thư mục album",
    "从列表删除时同时删除本地文件": "Xóa file máy khi xóa khỏi danh sách",
    "缓存管理:": "Bộ nhớ đệm:",
    "缓存文件存放路径（更改路径将于下次重启系统后生效）": "Thư mục cache (đổi sau khi khởi động lại)",
    "清理缓存": "Xóa cache",
    "一键清理": "Xóa ngay",
    "开启老板键": "Bật phím ẩn nhanh",
    "功能": "Tính năng",
    "消息通知:": "Thông báo:",
    "接收预约上线提醒": "Nhận nhắc lịch phát",
    "接收内容推荐提醒": "Nhận gợi ý nội dung",
    "版本更新:": "Cập nhật bản:",
    "随时保持最新": "Luôn bản mới nhất",
    "有更新时提醒我": "Nhắc khi có bản mới",
    "顶导航:": "Thanh trên:",
    "显示少儿模式": "Hiện chế độ trẻ em",
    "显示天气": "Hiện thời tiết",
    "音频设置：": "Âm thanh:",
    "输出设备：": "Thiết bị ra:",
    "显卡设置：": "Card đồ họa:",
    "选择显卡：": "Chọn card:",
    "解码设置：": "Cài đặt giải mã:",
    "智能解码": "Giải mã thông minh",
    "（推荐）": "(nên dùng)",
    "根据电脑配置自动选择最合适的解码方式": "Tự chọn cách giải mã phù hợp máy",
    "软件解码": "Giải mã mềm",
    "兼容性好，但高清晰度时内存占用较高": "Tương thích tốt, tốn RAM khi nét cao",
    "硬件解码": "Giải mã phần cứng",
    "性能更好，但在极少设备上可能会播放失败": "Mượt hơn; rất ít máy có thể lỗi phát",
    "片尾视频推荐：": "Gợi ý cuối tập:",
    "硬件加速：": "Tăng tốc phần cứng:",
    "显卡选择：": "Chọn card đồ họa:",
    "高帧率设置：": "Cài đặt FPS cao:",
    "智能调节": "Tự động",
    "根据电脑配置自动选择最合适的帧率设置": "Tự chọn FPS phù hợp máy",
    "开启高帧率": "Bật FPS cao",
    "默认开启高帧率，但部分设备可能会导致播放卡顿": "Bật FPS cao; máy yếu có thể giật",
    "关闭高帧率": "Tắt FPS cao",
    "当电脑性能不足时的最优选择": "Nên dùng khi máy yếu",
    "本地视频：": "Video máy:",
    "本地视频默认使用爱奇艺播放": "Mặc định phát video máy bằng iQIYI",
    "退出应用时清理本地播放列表和播放记录": "Xóa playlist và lịch sử khi thoát",
    "自动添加同路径相似文件到播放列表": "Tự thêm file cùng thư mục vào playlist",
    "定时关机：": "Hẹn giờ tắt:",
    "双击播放器：": "Nhấp đúp trình phát:",
    "全屏/标准 模式切换": "Đổi toàn màn / chuẩn",
    "小窗/标准 模式切换": "Đổi cửa sổ nhỏ / chuẩn",
    "画质增强：": "Tăng chất lượng:",
    "超分": "Siêu nét",
    "超帧": "Siêu khung hình",
    "（仅针对1080P清晰度生效）": "(chỉ với 1080P)",
    "视频加速：": "Tăng tốc video:",
    "开启视频加速服务": "Bật dịch vụ tăng tốc video",
    "开启GPU加速：": "Bật tăng tốc GPU:",
    "更改后需要重启客户端": "Đổi xong cần mở lại app",
    "本地视频默认使用爱奇艺视频播放": "Các video cục bộ được phát bằng iQiyi Video theo mặc định.",
    "退出应用时自动清理播放列表和最新的播放记录": "Tự động xóa danh sách phát và bản ghi phát lại mới nhất khi thoát khỏi ứng dụng",
    "基本设置": "Cơ bản",
    "下载设置": "Tải xuống",
    "其他设置": "Khác",
    "设置项重置": "Đặt lại cài đặt",
    "对所有的设置进行设置": "Lưu mọi cài đặt",
    "双击可以复制截图": "Nhấp đúp chuột để sao chép ảnh chụp màn hình",
    "矩形工具": "Hình chữ nhật",
    "圆形工具": "Hình tròn",
    "箭头工具": "Mũi tên",
    "画笔工具": "Công cụ cọ vẽ",
    "马赛克工具": "Che mờ",
    "文字工具": "Chữ",
    "撤销": "Hoàn tác",
    "退出截图": "Thoát chụp",
    "字号": "Cỡ chữ",
    "Copyright © 2026 爱奇艺 All Rights Reserved": "Copyright © 2026 iQIYI. Bảo lưu mọi quyền",
    "想了解更多信息? 请访问 ": "Muốn biết thêm thông tin? Thăm nom ",
    " 版本信息 ": " Thông tin phiên bản ",
    " 声明信息 ": " Thông tin sao kê ",
    "关联": "Liên kết",
    "始终保持文件关联": "Luôn gắn loại tệp",
    "自动文件关联后提示": "Nhắc sau khi liên kết tập tin tự động",
    "您可通过勾选更改关联": "Bạn có thể thay đổi liên kết bằng cách kiểm tra",
    "点击设置关联": "Nhấp vào Đặt liên kết",
    "您可以进入看图模式更改图片文件关联": "Bạn có thể vào chế độ xem ảnh để thay đổi liên kết tệp ảnh",
    "点击设置图片文件关联": "Bấm vào để thiết lập liên kết tập tin hình ảnh",
    "设置快捷键": "Đặt phím tắt",
    "去设置": "Tới cài đặt",
    "通用": "Chung",
    "基础设置": "Cài đặt cơ bản",
    "允许多开程序运行": "Cho phép chạy nhiều chương trình",
    "添加到系统右键菜单": "Thêm vào hệ thống menu chuột phải",
    "锁屏时暂停播放": "Tạm dừng phát lại khi màn hình bị khóa",
    "最小化时暂停播放": "Tạm dừng phát lại khi thu nhỏ",
    "启用自动续播功能": "Kích hoạt chức năng phát lại tự động",
    "启用硬件解码加速": "Bật giải mã phần cứng",
    "启用播放信息显示": "Bật hiển thị thông tin phát lại",
    "启用倍速设置全局生效": "Bật cài đặt tốc độ gấp đôi để có hiệu lực trên toàn cầu",
    "启用长按右方向键倍速播放": "Cho phép phát lại tốc độ gấp đôi bằng cách nhấn và giữ phím mũi tên phải",
    "启用鼠标悬停进度条预览画面": "Bật màn hình xem trước thanh tiến trình di chuột qua",
    "列表设置": "Cài đặt danh sách",
    "自动添加相似文件至播放列表": "Tự động thêm các tệp tương tự vào danh sách phát",
    "退出时清空播放列表和播放记录": "Xóa danh sách phát và lịch sử phát khi thoát",
    "文件关联": "liên kết tập tin",
    "设置文件关联": "Gắn loại tệp",
    "快进快退": "Chuyển tiếp nhanh và tua lại nhanh",
    "快进一次": "Chuyển nhanh một lần",
    "快退一次": "Tua lại một lần",
    "暂停时逐帧快进": "Chuyển tiếp nhanh từng khung hình trong khi tạm dừng",
    "窗口": "Cửa sổ",
    "截图": "Chụp màn hình",
    "投屏镜像-无线投屏": "Phản chiếu màn hình-Phản chiếu màn hình không dây",
    "投屏镜像-云投屏": "Phản chiếu màn hình-Phản chiếu màn hình đám mây",
    "无线投屏": "Quay màn hình không dây",
    "已开启": "Đã bật",
    "投屏设备名称：": "Tên thiết bị ghi màn hình:",
    "当前windows系统版本过低，无法使用云投屏功能，请将系统升级到win7及以上版本": "Windows hiện tại quá cũ nên không dùng được chiếu mây; hãy nâng cấp lên Win7 hoặc mới hơn.",
    "投屏码": "Mã chiếu",
    "加载中...": "Đang tải...",
    "扫码投屏": "Quét mã để truyền màn hình",
    "使用iOS最新版扫描二维码或输入投屏码即可投屏": "Dùng iOS mới nhất quét mã QR hoặc nhập mã chiếu để chiếu.",
    "当前热点：": "Chủ đề nóng hiện nay:",
    "将手机连入当前热点，投屏视频时选择本设备即可": "Kết nối điện thoại với điểm phát hiện tại; khi chiếu video, chọn thiết bị này.",
    "未找到当前电脑？": "Máy tính hiện tại không được tìm thấy?",
    "刷新试试~": "Hãy thử làm mới ~",
    "手机端如何使用投屏和镜像功能？": "Làm cách nào để sử dụng chức năng truyền và phản chiếu màn hình trên điện thoại di động?",
    "点此了解": "Bấm vào đây để tìm hiểu",
    "首次打开需要下载组件，请耐心等候": "Bạn cần tải các thành phần khi mở lần đầu tiên, hãy kiên nhẫn chờ đợi.",
    "组件加载中..": "Đang tải thành phần..",
    "组件加载失败，": "Tải thành phần không thành công,",
    "扫码安装APP": "Quét mã QR để cài đặt APP",
    "图片地址": "Địa chỉ ảnh",
    "更换": "Đổi",
    "图片格式": "Định dạng ảnh",
    "请选择播放器窗口样式": "Vui lòng chọn kiểu cửa sổ trình phát",
    "精简模式": "Chế độ gọn",
    "经典模式": "Cổ điển",
    "后续可在设置中更改": "Có thể đổi sau trong Cài đặt",
    "歌词": "Lời bài hát",
    "显示歌词": "hiển thị lời bài hát",
    "歌词路径": "đường dẫn lời bài hát",
    "与音乐文件同路径": "Cùng đường dẫn với file nhạc",
    "保存至指定路径": "Lưu vào đường dẫn đã chỉ định",
    "浏览": "Duyệt",
    "封面路径": "con đường che chắn",
    "媒体文件": "tập tin đa phương tiện",
    "启动应用时，窗口恢复上次大小及位置": "Khi ứng dụng được khởi chạy, cửa sổ sẽ khôi phục kích thước và vị trí cuối cùng của nó",
    "播放视频时": "Trong khi phát video",
    "窗口类型": "loại cửa sổ",
    "列表": "Danh sách",
    "退出时清空播放列表": "Xóa danh sách phát khi thoát",
    "退出时清空播放记录": "Xóa lịch sử khi thoát",
    "自动添加同路径下的相似文件到列表": "Tự động thêm các tệp tương tự theo cùng một đường dẫn vào danh sách",
    "快捷键（按退格键可取消设置）": "Phím tắt (Backspace để xóa)",
    "声卡选择": "Chọn card âm thanh",
    "请选择声卡": "Vui lòng chọn card âm thanh",
    "输出模式": "Chế độ đầu ra",
    "爱奇艺万能播放器": "Trình phát iQIYI",
    "程序遇到问题需要关闭，我们对此引起的不便深表歉意。": "Ứng dụng gặp sự cố và cần đóng. Chúng tôi xin lỗi vì sự bất tiện này.",
    "我们已经产生了一个关于此错误的报告，请您填写下方信息帮助我们改善": "Chúng tôi đã tạo báo cáo lỗi; hãy điền thông tin bên dưới để giúp cải thiện sản phẩm.",
    "产品质量": "Chất lượng sản phẩm",
    "重新启动程序": "Khởi động lại chương trình",
    "联系方式（QQ/手机/Email）": "Thông tin liên hệ (QQ/di động/Email)",
    "程序出错前您所做的操作：": "Những gì bạn đã làm trước khi xảy ra lỗi chương trình:",
    "查看错误报告详情": "Xem chi tiết báo cáo lỗi",
    "复制详情": "Sao chép chi tiết",
    "另存为文本": "Lưu thành văn bản",
    "如有问题请加QQ群：": "Nếu có thắc mắc gì hãy tham gia nhóm QQ:",
    "点击复制": "Bấm để sao chép",
    "，我们会有专人为您服务。": ", sẽ có người hỗ trợ bạn.",
    "发送错误报告": "Gửi báo cáo lỗi",
    "调试": "Gỡ lỗi",
    "错误报告详细信息：": "Chi tiết báo cáo lỗi:",
    "播放遇到问题？": "Gặp khó khăn khi chơi?",
    "需要咨询问题？请加QQ群：": "Cần một câu hỏi? Hãy tham gia nhóm QQ:",
    "提交": "Gửi",
    "感谢您的反馈!": "Cảm ơn phản hồi của bạn!",
    "我们会尽快为您处理": "Chúng tôi sẽ xử lý nó cho bạn sớm nhất có thể",
    "特别提示：": "Lời khuyên đặc biệt:",
    "1.为了解决问题，爱奇艺的工作人员可能会联系您": "1. Để xử lý vấn đề, nhân viên iQIYI có thể liên hệ với bạn",
    "立即重启": "Mở lại ngay",
    "置顶": "Ghim trên cùng",
    "当前系统时间": "Giờ hệ thống",
    "欢迎使用爱奇艺万能播放": "Chào mừng đến với iQiyi Universal Play",
    "编辑皮肤": "Chỉnh sửa da",
    "向左旋转90度": "Xoay 90 độ sang trái",
    "向右旋转90度": "Xoay phải 90°",
    "左右翻转": "Lật sang trái và phải",
    "缩小背景": "Thu nhỏ nền",
    "放大背景": "Phóng to trên nền",
    "正在播放": "Đang phát",
    "打开文件所在位置": "Mở vị trí tệp",
    "删除该条播放记录": "Xóa mục lịch sử phát này",
    "还没有播放记录": "Chưa có bản ghi phát lại nào",
    "清空全部": "Xóa tất cả",
    "播放列表文件过多，可能导致程序启动变慢，<n><p 5>是否需要清理？</p>": "Danh sách phát có quá nhiều tệp, có thể khiến app khởi động chậm.<n><p 5>Có muốn dọn dẹp không?</p>",
    "删除超过30天未播放的文件": "Xóa các tập tin không được phát trong hơn 30 ngày",
    "删除超过7天未播放的文件": "Xóa các tập tin không được phát trong hơn 7 ngày",
    "全部删除": "Xóa tất cả",
    "不删除": "Không xóa",
    "不再询问": "Không hỏi nữa",
    "从播放列表中删除": "Xóa khỏi danh sách phát",
    "类型:": "Loại:",
    "视频": "Video",
    "音频": "Âm thanh",
    "状态:": "Trạng thái:",
    "已播": "Đã phát",
    "未播": "Chưa phát",
    "搜索播放列表": "Tìm kiếm danh sách phát",
    "退出搜索": "Thoát tìm kiếm",
    "从列表移除": "Gỡ khỏi danh sách",
    "列表中暂时没有文件": "Hiện tại không có tập tin nào trong danh sách",
    "添加文件": "Thêm tệp",
    "暂无相关内容": "Chưa có nội dung liên quan",
    "上一次播放的文件": "Tệp vừa phát",
    "文件已失效": "Tệp không còn hiệu lực",
    "文件无效": "Tệp không hợp lệ",
    "打开URL": "Mở URL",
    "A-B循环播放": "Lặp A-B",
    "设置A点": "Đặt điểm A",
    "设置B点": "Đặt điểm B",
    "取消A-B循环播放": "Tắt lặp A-B",
    "设置片头点": "Đặt điểm intro",
    "跳过之前的片头内容": "Bỏ qua intro trước đó",
    "设置片尾点": "Đặt điểm outro",
    "跳过之后的片尾内容": "Bỏ qua outro sau đó",
    "取消跳过片头片尾": "Không bỏ qua intro/outro",
    "本次播放完成后": "Sau khi phát xong",
    "无动作": "Không làm gì",
    "关机": "Tắt máy",
    "锁屏": "Khóa màn hình",
    "睡眠": "Ngủ",
    "退出播放器": "Thoát trình phát",
    "查看文件信息": "Xem thông tin tệp",
    "清空播放列表": "Xóa danh sách phát",
    "移除失效文件": "Xóa các tập tin đã hết hạn",
    "添加文件夹": "Thêm thư mục",
    "添加URL": "Thêm URL",
    "最近播放": "Phát gần đây",
    "删除选中项": "Xóa mục đã chọn",
    "删除无效文件": "Xóa các tập tin không hợp lệ",
    "清除播放列表": "Xóa danh sách phát",
    "按名称排序": "Sắp xếp theo tên",
    "按大小排序": "Sắp xếp theo kích thước",
    "按类型排序": "Sắp xếp theo loại",
    "完整模式": "Chế độ đầy đủ",
    "显示界面": "giao diện hiển thị",
    "打开文件夹...  ": "Mở thư mục...  ",
    "打开URL...  ": "Mở URL...  ",
    "播放光盘": "chơi đĩa",
    "打开网盘...  ": "Mở đĩa mạng...  ",
    "快传... ": "Vượt qua nhanh... ",
    "设置片头": "Đặt intro",
    "设置片尾": "Đặt outro",
    "取消A-B重复": "Hủy sao chép A-B",
    "添加同路径相似文件到列表": "Thêm các tệp tương tự có cùng đường dẫn vào danh sách",
    "定位到列表所在位置": "Đi đến vị trí của danh sách",
    "打开所在文件夹": "Mở thư mục chứa nó",
    "按文件名升序": "Sắp xếp tăng dần theo tên tệp",
    "按文件名降序": "Sắp xếp giảm dần theo tên tệp",
    "显示主界面": "Hiển thị giao diện chính",
    "设置...  ": "cài đặt...  ",
    "关于...  ": "Về...  ",
    "画刷工具": "công cụ cọ vẽ",
    "重新选择截图区域        ": "Chọn lại vùng ảnh chụp màn hình        ",
    "隐藏工具栏": "Ẩn thanh công cụ",
    "主菜单编辑": "Chỉnh sửa menu chính",
    "发现新版本！": "Phiên bản mới được phát hiện!",
    "点击\"立即升级\"按钮将开始升级，之后程序会自动重启。": "Bấm nút \"Cập nhật ngay\" để bắt đầu; sau đó ứng dụng sẽ tự khởi động lại.",
    "以后再说": "Để sau",
    "正在检测新版本，请稍候.": "Đang phát hiện phiên bản mới, vui lòng đợi.",
    "收起列表栏": "Thu gọn thanh danh sách",
    "播放调节": "Điều chỉnh phát lại",
    "   抱歉，没找到歌词。": "   Xin lỗi, không tìm thấy lời bài hát.",
    "您可以尝试": "Bạn có thể thử",
    "载入歌词文件": "Tải tập tin lời bài hát",
    "正在搜索歌词，请稍候...": "Đang tìm kiếm lời bài hát, vui lòng đợi...",
    "投屏已断开": "Truyền màn hình đã bị ngắt kết nối",
    "与电视的链接断开了，请尝试重新投屏": "Liên kết tới TV bị hỏng, vui lòng thử truyền lại",
    "退出投屏": "Thoát ghi màn hình",
    "更换设备": "Thay thế thiết bị",
    "如果投屏失败，可能是连接的设备不支持该文件格式": "Nếu chiếu thất bại, thiết bị kết nối có thể không hỗ trợ định dạng này.",
    "截图保存": "Lưu ảnh chụp",
    "连拍截图": "Chụp liên tiếp",
    "播放控制": "Điều khiển phát",
    "音频调节": "Chỉnh âm",
    "字幕调节": "Chỉnh phụ đề",
    "退出全屏 ": "Thoát toàn màn hình ",
    "截图动画": "ảnh chụp màn hình hoạt hình",
    "啊哦~播放失败了": "Rất tiếc~Phát lại không thành công",
    "复制": "Sao chép",
    "失败原因:": "Lý do thất bại:",
    "错误码:": "Mã lỗi:",
    "说明:": "Mô tả:",
    "查看原因": "Xem lý do tại sao",
    "关闭提示": "Tắt gợi ý",
    "如有疑问，您可以": "Nếu nghi ngờ, bạn có thể",
    "点击这里": "bấm vào đây",
    "无法打开文件": "Không thể mở tập tin",
    "文件可能已损坏或文件格式不支持": "Tệp có thể bị hỏng hoặc định dạng tệp không được hỗ trợ",
    "使用爱奇艺客户端播放": "Chơi bằng ứng dụng khách iQiyi",
    "因版权原因，Win7及以下系统暂不支持该音频解码": "Vì lý do bản quyền, Win7 trở xuống tạm chưa hỗ trợ giải mã âm thanh này.",
    "建议您将系统升级到Win10": "Bạn nên nâng cấp hệ thống của mình lên Win10",
    "点此了解更多": "Bấm vào đây để tìm hiểu thêm",
    "播放信息显示": "Chơi hiển thị thông tin",
    "显示位置：": "Vị trí hiển thị:",
    "关闭显示": "Tắt hiển thị",
    "上方显示": "Hiện phía trên",
    "下方显示": "Hiện phía dưới",
    "显示信息：": "Hiển thị thông tin:",
    "文件名": "Tên tệp",
    "播放进度": "Tiến trình phát lại",
    "系统时间": "thời gian hệ thống",
    "视频帧率": "Tốc độ khung hình video",
    "电池电量": "Nguồn pin",
    "显示时机": "Hiển thị thời gian",
    "仅全屏时显示": "Chỉ hiển thị ở chế độ toàn màn hình",
    "始终显示": "Luôn hiển thị",
    "显示边距": "hiển thị lề",
    "默认": "Mặc định",
    "紧贴边缘": "ôm lấy mép",
    "GIF截图": "Chụp GIF",
    "GIF尺寸": "kích thước GIF",
    "截取时长": "Thời gian chặn",
    "10.0秒": "10,0 giây",
    "减少0.1秒": "Giảm 0,1 giây",
    "增加0.1秒": "Thêm 0,1 giây",
    "截取间隔": "khoảng thời gian đánh chặn",
    "100毫秒": "100 mili giây",
    "截取位置": "Vị trí chặn",
    "保存路径": "lưu đường dẫn",
    "预览": "Xem trước",
    "停止": "Dừng",
    "分享到微博": "Chia sẻ lên weibo",
    "请输入您想要添加的URL地址": "Vui lòng nhập địa chỉ URL bạn muốn thêm",
    "目前支持http,mms,rtsp三种协议": "Hiện hỗ trợ ba giao thức http, mms, rtsp",
    "清空URL列表": "Xóa danh sách URL",
    "清空URL列表中的历史数据": "Xóa dữ liệu lịch sử trong danh sách URL",
    "声音调节": "Chỉnh âm",
    "添加音轨": "Thêm bản âm thanh",
    "本视频暂无音轨": "Video này chưa có bản âm thanh",
    "音轨延迟(s)": "Theo dõi độ trễ",
    "声道选择": "Chọn kênh âm",
    "亮度": "Độ sáng",
    "对比度": "Tương phản",
    "饱和度": "Bão hòa",
    "色相": "Hue",
    "画面旋转": "Xoay màn hình",
    "向左旋转": "Xoay trái",
    "向右旋转": "Xoay phải",
    "水平翻转": "Lật ngang",
    "垂直翻转": "Lật dọc",
    "步进定位": "định vị bước",
    "时间定位": "định vị thời gian",
    "请输入正确的定位时间": "Vui lòng nhập đúng thời gian định vị",
    "跳转": "Chuyển đến",
    "播放速度": "tốc độ chơi",
    "当前速度:1.0倍": "Tốc độ hiện tại: 1.0x",
    "播放速度设置始终生效": "Giữ tốc độ phát",
    "重置": "Đặt lại",
    "添加字幕": "Thêm phụ đề",
    "本视频暂无字幕": "Video này chưa có phụ đề",
    "字幕延迟(s)": "(Các) độ trễ phụ đề",
    "字幕位置": "Vị trí phụ đề",
    "底部": "Bên dưới",
    "顶部": "Bên trên",
    "字幕字体": "phông chữ phụ đề",
    "字幕字号": "Kích thước phông chữ phụ đề",
    "字幕颜色": "Màu phụ đề",
    "字幕描边": "đột quỵ phụ đề",
    "描边颜色": "màu đột quỵ",
    "文件信息": "Thông tin tập tin",
    "文件名.avi": "tên tập tin.avi",
    "基本信息": "Thông tin cơ bản",
    "文件类型:": "Loại tập tin:",
    "文件时长:": "Thời lượng tập tin:",
    "文件大小:": "Kích thước tập tin:",
    "文件码率:": "Tốc độ bit của tệp:",
    "文件位置:": "Vị trí tập tin:",
    "视频信息": "Thông tin video",
    "视频编码:": "Mã hóa video:",
    "视频码率:": "Tốc độ bit video:",
    "视频帧率:": "Tốc độ khung hình video:",
    "分辨率:": "Nghị quyết:",
    "音频信息": "thông tin âm thanh",
    "音频编码:": "Mã hóa âm thanh:",
    "音频码率:": "Tốc độ bit âm thanh:",
    "声道数:": "Số kênh:",
    "当前时间": "thời điểm hiện tại",
    "剩余时间：": "thời gian còn lại:",
    "定时动作：": "Hành động theo thời gian:",
    "立即执行": "Thực hiện ngay lập tức",
    "取消执行": "Hủy thực thi",
    "音频同步": "đồng bộ hóa âm thanh",
    "音频同步（毫秒）：": "Đồng bộ hóa âm thanh (mili giây):",
    "声音延后": "Trễ âm",
    "声音提前": "Sớm âm",
    "当前状态：": "Tình trạng hiện tại:",
    "未设置": "Chưa đặt",
    "自定义": "Tùy chỉnh",
    "饱和度/鲜艳度": "Độ bão hòa/Sức sống",
    "明亮": "Sáng",
    "柔和": "Mềm",
    "复古": "Cổ điển",
    "始终保持以上设置效果": "Luôn giữ hiệu ứng trên",
    "比例": "Tỷ lệ",
    "原始": "Gốc",
    "铺满": "Lấp đầy",
    "旋转": "Xoay",
    "左旋90度": "90 độ trái",
    "右旋90度": "Quay phải 90 độ",
    "开启跳过片头片尾": "Bật bỏ qua phần tín dụng mở đầu và kết thúc",
    "跳过片头：": "Bỏ qua tiêu đề:",
    "秒": "giây",
    "跳过片尾：": "Bỏ qua phần kết:",
    "投屏到电视": "Chiếu TV",
    "正在搜索投屏设备…": "Đang tìm kiếm thiết bị phản chiếu màn hình…",
    "确保当前设备与投屏接收方 (电视等设备) 处于同一WiFi下": "Đảm bảo thiết bị hiện tại và thiết bị nhận chiếu (TV...) dùng cùng Wi‑Fi.",
    "设备列表": "Danh sách thiết bị",
    "未发现设备": "Không thấy thiết bị",
    "内容": "Nội dung",
    "否": "Không",
    "使用手机已登录账号快捷登录": "Đăng nhập nhanh chóng bằng tài khoản đã đăng nhập trên điện thoại di động của bạn",
    "使用此账号一键登录": "Sử dụng tài khoản này để đăng nhập bằng một cú nhấp chuột",
    "手机授权登录": "Đăng nhập được ủy quyền bằng điện thoại di động",
    "使用其他账号登录": "Đăng nhập tài khoản khác",
    "同意": "Đồng ý",
    "《用户协议》": "Điều khoản",
    "和": "và",
    "《隐私条款》": "Chính sách riêng tư",
    "请阅读并勾选下方协议": "Hãy đọc và tick điều khoản bên dưới",
    "常用地区": "Khu vực thường dùng",
    "安全验证": "Xác minh bảo mật",
    "当前会员账号已在多个设备上登录": "Tài khoản VIP đang đăng nhập nhiều máy",
    "为了您的会员权益和数据安全": "Vì quyền thành viên và bảo mật dữ liệu của bạn",
    "无法在当前设备登录": "Không thể đăng nhập trên thiết bị hiện tại",
    "切换账号登录>": "Đổi tài khoản >",
    "为了会员权益和数据安全": "Đối với quyền thành viên và bảo mật dữ liệu",
    "请使用以下方式进行验证登录": "Vui lòng sử dụng phương pháp sau để xác minh đăng nhập",
    "主设备扫码验证": "Máy chính quét mã xác minh",
    "发送短信进行验证": "Gửi SMS để xác minh",
    "第三方授权验证": "Xác minh ủy quyền của bên thứ ba",
    "当前登录存在风险": "Thông tin đăng nhập hiện tại của bạn đang gặp rủi ro",
    "为了您的账号安全": "Để bảo mật tài khoản của bạn",
    "请打开": "Hãy mở",
    "爱奇艺手机APP": "App iQIYI điện thoại",
    "请在手机上授权登录": "Xác nhận đăng nhập trên điện thoại",
    "前往短信登录>": "Vào phần đăng nhập SMS >",
    "删除账号后": "Sau khi xóa tài khoản",
    "再次登录需重新验证": "Đăng nhập lại yêu cầu xác minh lại.",
    "账号已被冻结": "Tài khoản đã bị đóng băng",
    "您的账号已开启设备锁": "Khóa thiết bị đã được bật cho tài khoản của bạn",
    "您的账号开启了设备锁": "Khóa thiết bị được bật trên tài khoản của bạn",
    "快速登录": "Đăng nhập nhanh",
    "点击头像快速登录": "Bấm vào avatar để đăng nhập nhanh",
    "欢迎来到爱奇艺": "Chào mừng đến với iQiyi",
    "登录后解锁更多功能": "Đăng nhập để mở khóa nhiều tính năng hơn",
    "短信登录": "đăng nhập qua tin nhắn SMS",
    "密码登录": "Mật khẩu",
    "忘记密码": "Quên mật khẩu",
    "其他登录方式": "Các phương thức đăng nhập khác",
    "未注册过的手机号，我们将自动帮您注册账号": "Đối với số điện thoại di động chưa đăng ký, chúng tôi sẽ tự động đăng ký tài khoản cho bạn.",
    "开通会员享特权": "Trở thành thành viên và tận hưởng các đặc quyền",
    "超多特权一键解锁": "Mở khóa nhiều đặc quyền chỉ bằng một cú nhấp chuột",
    "广告特权": "đặc quyền quảng cáo",
    "热剧抢先看": "Xem phim truyền hình nóng đầu tiên",
    "蓝光1080P": "Blu-ray 1080P",
    "电影点播券": "Phiếu giảm giá phim theo yêu cầu",
    "确定退出当前账号吗": "Bạn có chắc chắn muốn đăng xuất khỏi tài khoản hiện tại của mình không?",
    "记住账号下次快速登录": "Nhớ tài khoản để đăng nhập nhanh lần sau",
    "确定退出": "Được rồi để thoát",
    "注册账号": "Đăng ký tài khoản",
    "为了您的账号安全，请绑定一个手机号": "Để bảo mật tài khoản của bạn, vui lòng liên kết số điện thoại di động",
    "为保证您的账号安全，请完成一下认证": "Để đảm bảo tính bảo mật cho tài khoản của bạn, vui lòng hoàn tất xác thực sau",
    "正在为您加载...": "Đang tải...",
    "数据加载失败": "Tải dữ liệu không thành công",
    "发送短信验证": "Gửi xác minh qua SMS",
    "您接收的短信验证码次数已达上限": "Số lượng mã xác minh SMS bạn nhận được đã đạt đến giới hạn trên.",
    "为了您的账户安全，请发送短信验证": "Để bảo mật tài khoản của bạn, vui lòng gửi xác minh SMS",
    "修改": "Sửa đổi",
    "请编辑短信": "Vui lòng chỉnh sửa tin nhắn",
    "发送到号码": "gửi đến số",
    "我已经发送了": "tôi đã gửi",
    "已超时，请刷新": "Đã hết thời gian, vui lòng làm mới",
    "为了您的账号安全，请设置手机号": "Để bảo mật tài khoản của bạn, vui lòng đặt số điện thoại di động",
    "手机号已被微信账号绑定，仅可作为本账号的登录身份验证，不能绑定本账号。": "Số điện thoại đã liên kết với tài khoản WeChat, chỉ dùng để xác minh đăng nhập tài khoản này, không thể liên kết lại.",
    "继续登录": "Tiếp tục đăng nhập",
    "绑定其他手机号": "Liên kết các số điện thoại di động khác",
    "打开本地文件": "Mở file máy",
    "小窗模式": "Cửa sổ nhỏ",
    "窗口置顶": "Ghim cửa sổ",
    "画面缩放": "Thu phóng hình ảnh",
    "铺满(保持比例)": "Lấp đầy (giữ tỷ lệ)",
    "铺满(拉伸画面)": "Lấp đầy (kéo giãn)",
    "铺满（保持比例）": "Lấp đầy (giữ nguyên tỷ lệ)",
    "铺满（拉伸画面）": "Lấp đầy (kéo giãn khung hình)",
    "原始尺寸": "Kích thước gốc",
    "截图分享": "Chụp & chia sẻ",
    "全屏模式 Alt + Enter": "Chế độ toàn màn hình Alt + Enter",
    "精简模式 Ctrl + M": "Chế độ thu gọn Ctrl + M",
    "默认布局": "bố cục mặc định",
    "窗口置顶 Alt + Z": "Giữ cửa sổ ở trên cùng Alt + Z",
    "影片原始尺寸": "Kích thước video gốc",
    "保持原有比例": "Giữ tỷ lệ ban đầu",
    "声道": "Kênh âm",
    "左声道": "Kênh trái",
    "右声道": "Kênh phải",
    "投屏播放": "Phát lại màn hình truyền",
    "定时": "Hẹn giờ",
    "在线帮助": "Trợ giúp online",
    "已保存至:": "Đã lưu vào:",
    "打开文件位置": "Mở vị trí tệp",
    "分享至:": "Chia sẻ tới:",
    "分享到QQ好友": "Chia sẻ với bạn bè QQ",
    "分享到新浪微博": "Chia sẻ lên Sina weibo",
    "分享到QQ空间": "Chia sẻ lên không gian QQ",
    "弹幕显示设置": "Cài đặt hiển thị bình luận chạy",
    "重置弹幕显示设置": "Đặt lại cài đặt hiển thị bình luận chạy",
    "不透明度": "Độ mờ",
    "标准": "Chuẩn",
    "速度": "Tốc độ",
    "智能防剧透": "Chống spoiler thông minh",
    "屏蔽更多潜在剧透弹幕": "Chặn thêm bình luận chạy có thể tiết lộ nội dung",
    "0级": "Cấp 0",
    "默认开启弹幕": "Mặc định bật bình luận chạy",
    "屏蔽设置": "Chặn",
    "屏蔽后新出现的弹幕均为白色": "Bình luận chạy mới sẽ có màu trắng sau khi chặn",
    "彩色": "Màu",
    "开启后弹幕将不再遮挡人像区域": "Bật để bình luận chạy không che khuôn mặt",
    "人像区域": "Vùng khuôn mặt",
    "设置屏蔽词": "Từ chặn",
    "没有更多了...": "Không còn nữa...",
    "加载失败": "Tải lỗi",
    "请选择举报原因": "Vui lòng chọn lý do báo cáo",
    "提 交": "Gửi",
    "添加": "Thêm",
    "已有相同内容哦～": "Đã có nội dung tương tự rồi~",
    "添加后将看不到含此词的弹幕哦～": "Sau khi thêm, bạn sẽ không thấy bình luận chạy có chứa từ này.",
    "刷新重试": "Hãy làm mới và thử lại",
    "哈哈哈哈哈": "Hahahahaha",
    "弹幕发送设置": "Cài đặt gửi bình luận chạy",
    "注册": "Đăng ký",
    "发送弹幕": "Gửi bình luận chạy",
    "角色弹幕": "Bình luận chạy theo nhân vật",
    "弹幕来一波…": "Gửi bình luận chạy thôi…",
    "弹幕走一波...": "Gửi bình luận chạy thôi...",
    "最多5个字符，回车可添加": "Tối đa 5 ký tự, nhấn Enter để thêm",
    "爱奇艺,客户端下载,下载": "iQIYI, tải ứng dụng, tải xuống",
    "爱奇艺客户端下载页面。": "Trang tải ứng dụng iQIYI.",
    "爱奇艺-在线视频网站-海量正版高清视频在线观看": "iQIYI – Xem video trực tuyến, kho nội dung bản quyền chất lượng cao",
    "爱奇艺-客户端下载": "Tải ứng dụng iQIYI",
    "爱奇艺-sleep": "iQIYI – Đang tạm nghỉ",
    "页面加载失败，请重新": "Trang không tải được, vui lòng",
    "404错误页页": "Trang lỗi 404",
    "Internet Explorer 无法显示该网页": "Internet Explorer không thể hiển thị trang này.",
    "您可以尝试以下操作:": "Bạn có thể thử những cách sau:",
    "您可能已经连接到 Internet，但您可能希望尝试重新连接到 Internet。": "Có thể bạn đã kết nối Internet, nhưng hãy thử kết nối lại.",
    "最可能的原因是:": "Nguyên nhân có thể là:",
    "未连接到 Internet。": "Chưa kết nối Internet.",
    "该网站遇到了问题": "Trang web đang gặp sự cố.",
    "重新刷新网页。": "Hãy tải lại trang.",
    "若您已经连接到Internet，请重新": "Nếu bạn đã kết nối Internet, hãy",
    "搜视频...": "Tìm video...",
    "清空搜索内容": "Xóa nội dung tìm kiếm",
    "已为您找到相关结果，问问AI快速总结重点": "Đã tìm thấy kết quả phù hợp. Hỏi AI để tóm tắt nhanh nội dung chính.",
    "问一问AI": "Hỏi AI",
    "综合": "Tổng hợp",
    "用户": "Người dùng",
    "立即播放": "Phát ngay",
    "大家还爱看": "Mọi người cũng thích xem",
    "相关短视频": "Video ngắn liên quan",
    "卫视": "Kênh truyền hình vệ tinh",
    "都市爱情": "Tình yêu đô thị",
    "内地": "Trung Quốc đại lục",
    "今日更新": "Cập nhật hôm nay",
    "筛选": "Lọc",
    "免费": "Miễn phí",
    "中剧": "Phim thời lượng vừa",
    "少儿": "Thiếu nhi",
    "漫剧": "Phim hoạt họa truyện tranh",
    "动画": "Hoạt hình",
    "枪战": "Đấu súng",
    "警匪": "Cảnh sát - tội phạm",
    "灾难": "Thảm họa",
    "传记": "Tiểu sử",
    "伦理": "Tâm lý xã hội",
    "运动": "Thể thao",
    "魔幻": "Phép thuật",
    "歌舞": "Ca vũ",
    "戏曲": "Kịch hát truyền thống",
    "玄幻": "Huyền huyễn",
    "悲剧": "Bi kịch",
    "西部": "Miền Tây",
    "史诗": "Sử thi",
    "英国": "Vương quốc Anh",
    "时间": "Thời gian",
    "资费": "Hình thức xem",
    "近期转免": "Mới chuyển sang miễn phí",
    "免费解锁VIP": "Mở khóa nội dung VIP miễn phí",
    "竞技": "Tranh tài",
    "谍战": "Tình báo",
    "警匪罪案": "Tội phạm - hình sự",
    "家庭伦理": "Tâm lý gia đình",
    "女频": "Nội dung dành cho khán giả nữ",
    "男频": "Nội dung dành cho khán giả nam",
    "怀旧情感": "Tình cảm hoài niệm",
    "年代": "Bối cảnh thời đại",
    "女性成长": "Hành trình trưởng thành của phụ nữ",
    "法制": "Đề tài pháp luật",
    "都市": "Đô thị",
    "生活": "Đời sống",
    "军旅题材": "Đề tài quân ngũ",
    "战友情": "Tình đồng đội",
    "抗日战争": "Kháng chiến chống Nhật",
    "当代谍战": "Tình báo hiện đại",
    "竞演": "Tranh tài biểu diễn",
    "飞天奖": "Giải Phi Thiên",
    "反特谍战": "Phản gián - điệp chiến",
    "悬疑推理": "Trinh thám, bí ẩn",
    "情感悬疑": "Tình cảm, bí ẩn",
    "战争传奇": "Huyền thoại chiến tranh",
    "扫黑缉毒": "Trấn áp tội phạm và ma túy",
    "家长里短": "Chuyện thường nhật trong gia đình",
    "刑侦破案": "Điều tra hình sự",
    "科幻末世": "Khoa học viễn tưởng hậu tận thế",
    "都市日常": "Đời sống đô thị",
    "青春校园": "Thanh xuân học đường",
    "男性传奇": "Truyền kỳ nam giới",
    "抗战谍战": "Điệp chiến thời kháng chiến",
    "强强联合": "Kết hợp ngang tài",
    "穿越": "Xuyên không",
    "美食": "Ẩm thực",
    "都市喜剧": "Hài đô thị",
    "古风权谋": "Đấu trí quyền mưu cổ trang",
    "总裁": "Tổng tài",
    "战神归来": "Chiến thần trở lại",
    "10年代": "Thập niên 2010",
    "00年代": "Thập niên 2000",
    "90年代": "Thập niên 1990",
    "80年代": "Thập niên 1980",
    "通知": "Thông báo",
    "点赞": "Lượt thích",
    "在追": "Đang theo dõi",
    "钱包": "Ví tiền",
    "关闭验证": "Đóng xác minh",
    "刷新验证": "Làm mới xác minh",
    "请输入您听到的内容": "Nhập nội dung bạn nghe được",
    "试看已结束，继续观看请开通VIP会员": "Đã hết thời gian xem thử. Đăng ký VIP để xem tiếp.",
    "未开通会员，不能观看海量VIP内容": "Bạn chưa đăng ký VIP nên chưa xem được kho nội dung VIP.",
    "更多开通选择": "Xem thêm gói hội viên",
    "黄金VIP": "VIP Vàng",
    "白金VIP": "VIP Bạch Kim",
    "星钻VIP": "VIP Kim Cương",
    "广告特权+五端可用": "Không quảng cáo + dùng được trên 5 thiết bị",
    "高清投屏+七端通(含电视)": "Chiếu màn hình chất lượng cao + dùng trên 7 thiết bị (gồm TV)",
    "加更礼免费看+七端通": "Xem miễn phí nội dung tặng thêm + dùng trên 7 thiết bị",
    "连续包年": "Gia hạn tự động hằng năm",
    "大促红包": "Voucher khuyến mãi",
    "连续包月": "Gia hạn tự động hằng tháng",
    "双月卡": "Gói 2 tháng",
    "惊喜半价特惠": "Ưu đãi bất ngờ giảm nửa giá",
    "连续包季": "Gia hạn tự động theo quý",
    "年卡": "Gói năm",
    "双11大促": "Đại ưu đãi 11/11",
    "季卡": "Gói quý",
    "月卡": "Gói tháng",
    "赠送以下权益": "Quyền lợi được tặng kèm",
    "黄金VIP会员15天": "15 ngày VIP Vàng",
    "会员特权对比": "So sánh quyền lợi VIP",
    "个人标准": "Gói cá nhân",
    "家庭标准": "Gói gia đình",
    "家庭高端": "Gói gia đình cao cấp",
    "热播内容": "Nội dung nổi bật",
    "会员抢先看": "Xem trước nội dung VIP",
    "适用终端": "Thiết bị hỗ trợ",
    "同时播放": "Phát đồng thời",
    "同时登录": "Đăng nhập đồng thời",
    "会员积分": "Điểm VIP",
    "本页展示的划线价为建议零售价": "Giá gạch ngang trên trang là giá bán lẻ đề xuất.",
    "代金券": "Phiếu giảm giá",
    "暂无可用": "Chưa có phiếu khả dụng",
    "《会员协议》": "“Thỏa thuận hội viên”",
    "新朋友，开通享精彩内容": "Đăng ký VIP để khám phá nhiều nội dung hấp dẫn",
    "共减": "Tổng tiết kiệm",
    "热搜": "Tìm kiếm nổi bật",
    "热点": "Chủ đề nóng",
    "搜索推荐": "Đề xuất tìm kiếm",
    "选择不考虑观看的原因：": "Chọn lý do bạn không muốn xem:",
    "选择不考虑观看的原因:": "Chọn lý do bạn không muốn xem:",
    "已看过": "Đã xem",
    "重复推荐": "Được đề xuất nhiều lần",
    "就是不想看": "Tôi không muốn xem",
    "甜宠": "Ngọt sủng",
    "暗恋成真": "Thầm yêu thành đôi",
    "打脸虐渣": "Vả mặt kẻ xấu",
    "现代言情": "Ngôn tình hiện đại",
    "闪婚": "Cưới chớp nhoáng",
    "虐恋": "Tình yêu ngược",
    "破镜重圆": "Gương vỡ lại lành",
    "先婚后爱": "Cưới trước, yêu sau",
    "东方玄幻": "Huyền huyễn phương Đông",
    "恋爱": "Tình yêu",
    "恋爱脑": "Lụy tình",
    "百姓趣闻": "Chuyện đời thường thú vị",
    "农村": "Nông thôn",
    "御兽": "Ngự thú",
    "废柴": "Phế vật",
    "上传": "Tải lên",
    "爆": "Bùng nổ",
    "热": "Đang hot",
    "预": "Sắp chiếu",
    "迷雾剧场": "Rạp Sương Mù",
    "大家剧场": "Rạp Phim Đại Chúng",
    "恋恋剧场": "Rạp Phim Tình Cảm",
    "小逗剧场": "Rạp Hài",
    "查看全部内容": "Xem toàn bộ nội dung",
    "风云榜总榜": "Bảng xếp hạng tổng hợp",
    "查看完整风云榜": "Xem đầy đủ bảng xếp hạng",
    "画质": "Chất lượng hình ảnh",
    "黄金/白金/星钻VIP尊享": "Dành riêng cho VIP Vàng, Bạch Kim và Kim Cương",
    "超高清4K": "Siêu nét 4K",
    "准高清": "Gần HD",
    "智能": "Thông minh",
    "自动调节画质": "Tự động điều chỉnh chất lượng hình ảnh",
    "音效": "Hiệu ứng âm thanh",
    "（VIP音效限黄金/白金/星钻VIP）": "(Hiệu ứng âm thanh VIP chỉ dành cho VIP Vàng, Bạch Kim và Kim Cương)",
    "分集视频标题": "Hiển thị tiêu đề tập phim",
    "长按倍速": "Nhấn giữ để tăng tốc",
    "天才医生跌落神坛，小城行医暖人心": "Bác sĩ thiên tài sa cơ, hành nghề ở thị trấn nhỏ, sưởi ấm lòng người",
    "跳过广告": "Bỏ qua quảng cáo",
    "免费集将看完": "Sắp hết số tập được xem miễn phí",
    "开会员看全集": "Đăng ký VIP để xem trọn bộ",
    "Truc Ngoc": "Trục Ngọc",
    "沈诺蔓儿制定救人计划": "Thẩm Nặc và Liên Mạn Nhi lập kế hoạch cứu người",
    "客户端4K播放": "Phát 4K trên ứng dụng",
    "播单": "Danh sách phát",
    "黄金关闭此广告": "VIP Vàng có thể tắt quảng cáo",
    "关闭此广告": "Tắt quảng cáo này",
    "新婚当晚被关柴房！她被养兄长骗嫁为妾": "Đêm tân hôn bị nhốt trong nhà củi! Nàng bị anh nuôi lừa gả làm thiếp",
    "《田耕纪》腹黑大姐连花儿，嫁人了也不安...": "Chị cả Liên Hoa mưu mô trong “Điền Canh Kỷ”, lấy chồng rồi vẫn chưa yên...",
    "种田电子榨菜大全": "Tuyển tập video giải trí đề tài làm ruộng",
    "了解详情": "Xem chi tiết",
    "点击一下，快速跳过广告": "Nhấn một lần để bỏ qua quảng cáo",
    "▶ 跳过广告观看正片": "▶ Bỏ qua quảng cáo để xem phim",
    "跳过广告观看正片": "Bỏ qua quảng cáo để xem phim",
    "打开广告落地页": "Mở trang quảng cáo",
    "已切换主字幕为": "Đã chuyển phụ đề chính sang ",
    "分": "điểm",
    "本剧全集免费看": "Xem miễn phí toàn bộ phim này",
    "番外": "Ngoại truyện",
    "为了更好处理您的反馈与建议，请填写QQ号/微信号": "Để hỗ trợ phản hồi của bạn tốt hơn, vui lòng nhập ID QQ hoặc WeChat.",
    "请填写意见建议": "Vui lòng nhập ý kiến góp ý.",
    "请输入": "Vui lòng nhập",
    "请输入密码": "Nhập mật khẩu",
    "请输入手机号": "Nhập số điện thoại",
    "请输入手机号/邮箱": "Nhập số điện thoại/email",
    "请输入验证码": "Nhập mã xác minh",
    "返回主窗口": "Trở về cửa sổ chính",
    "速看": "Xem nhanh",
    "详情": "Chi tiết",
    "加追": "Theo dõi",
    "开会员立享": "Đăng ký VIP, hưởng ưu đãi ngay",
    "长剧": "Phim dài tập",
    "短剧": "Phim ngắn",
    "精彩短视频": "Video ngắn nổi bật",
    "讨论": "Thảo luận",
    "二创": "Sáng tạo lại",
    "彩色文字": "Văn bản màu",
    "尊敬的用户": "Kính gửi người dùng",
    "由于运营商劫持，您的爱奇艺客户端暂时无法正常运行。": "Do nhà mạng can thiệp, app iQIYI tạm thời không chạy bình thường.",
    "请尽快联系您的运营商！": "Vui lòng liên hệ với nhà cung cấp dịch vụ của bạn càng sớm càng tốt!",
    "请将以下地址告知我们:": "Vui lòng thông báo cho chúng tôi địa chỉ sau:",
    "单击可进行复制": "Bấm để sao chép",
    "加入QQ群:": "Tham gia nhóm QQ:",
    "拨打24小时客服电话:": "Gọi tới đường dây nóng dịch vụ khách hàng 24/24:",
    "举报原因:": "Lý do báo cáo:",
    "其他原因:": "Lý do khác:",
    "循环播放": "Phát lặp",
    "隔空手势": "Điều khiển bằng cử chỉ",
    "常用快捷键": "Phím tắt thường dùng",
    "老板键": "Phím ẩn nhanh",
    "全屏/退出全屏": "Toàn màn hình/Thoát toàn màn hình",
    "Alt + 回车": "Alt + Enter",
    "播放/暂停": "Phát/Tạm dừng",
    "空格": "Phím cách",
    "快进（长按开启倍速）": "Tua nhanh (nhấn giữ để tăng tốc)",
    "快退": "Tua lùi",
    "增加音量": "Tăng âm lượng",
    "降低音量": "Giảm âm lượng",
    "全部快捷键": "Tất cả phím tắt",
    "播放问题诊断": "Chẩn đoán lỗi phát",
    "更多设置": "Cài đặt khác",
    "查看列表": "Xem danh sách",
    "更换皮肤": "Đổi giao diện",
    "列表透明度": "Độ trong suốt danh sách",
    "调节播放列表透明度（仅能调节非播放时的列表状态）": "Chỉnh độ trong suốt danh sách phát (chỉ áp dụng khi không phát).",
    "控制区域透明度": "Độ trong suốt vùng điều khiển",
    "调节控制区域透明度": "Chỉnh độ trong suốt vùng điều khiển",
    "纯色": "Màu đơn",
    "品牌图片": "Ảnh thương hiệu",
    "自定义图片": "Ảnh tùy chọn",
    "恢复默认界面": "Khôi phục giao diện mặc định",
    "歌词字体放大": "Tăng cỡ chữ lời bài hát",
    "歌词字体缩小": "Giảm cỡ chữ lời bài hát",
    "歌词时间提前": "Hiển thị lời bài hát sớm hơn",
    "歌词时间延后": "Hiển thị lời bài hát muộn hơn",
    "缩小": "Thu nhỏ",
    "放大": "Phóng to",
    "音乐模式": "Chế độ âm nhạc",
    "上一个文件": "Tệp trước",
    "下一个文件": "Tệp tiếp",
    "使用主设备打开爱奇艺": "Mở iQIYI trên thiết bị chính",
    "点击页面右上角“+”-“扫一扫” ": "Nhấn “+” ở góc trên bên phải rồi chọn “Quét mã” ",
    "扫描下方二维码，授权登录": "Quét mã QR bên dưới để cho phép đăng nhập",
    "请阅读并同意": "Vui lòng đọc và đồng ý",
    "《隐私政策》": "“Chính sách quyền riêng tư”",
    "同意并登录": "Đồng ý và đăng nhập",
    "（仅针对720P及以下清晰度生效）": "(Chỉ áp dụng cho chất lượng 720P trở xuống)",
    "（仅针对1080P及以下清晰度生效）": "(Chỉ áp dụng cho chất lượng 1080P trở xuống)",
    "《》等11个视频下载完成": "Đã tải xong 11 video, gồm «»",
    "<c #ffffff>感谢您选择爱奇艺PC客户端！</c><c #ffffff><n><n> </c><c #ffffff><n ><n>我们非常重视您的个人信息和隐私保护。为了更好地保障您的个人权益，在您使用我们的产品前，请务必审慎阅读</c><a https://www.iqiyi.com/user/register/protocol.html><c #00b909>《爱奇艺服务协议》</c></a><c #ffffff>与</c><a https://privacy.iqiyi.com/policies><c #00b909>《爱奇艺隐私政策》</c></a><c #ffffff>内的所有条款，尤其是:</c><c #ffffff><n> </c>\r\n<c #ffffff><n>1. 我们对您的个人信息的收集/保存/使用/对外提供/保护等规则条款，以及您的用户权利等条款；</c>\r\n<c #ffffff><n>2. 约定我们的限制责任、免责条款；</c><c #ffffff><n>3. 其他以颜色或加粗进行标识的重要条款。<n></c><c #ffffff><n> </c><c #ffffff><n>如您对以上协议有任何疑问，可通过人工客服或发邮件至 privacy＠qiyi.com与我们联系。您点击“同意并继续”的行为即表示您已阅读完毕并同意以上协议的全部内容。</c><c #ffffff><n> <n>如您同意以上协议内容，请点击“同意并继续”，开始使用我们的产品和服务！</c>": "<c #ffffff>Cảm ơn bạn đã chọn ứng dụng iQIYI cho máy tính!</c><c #ffffff><n><n> </c><c #ffffff><n ><n>Chúng tôi rất coi trọng việc bảo vệ thông tin cá nhân và quyền riêng tư của bạn. Để bảo vệ quyền lợi của mình, trước khi sử dụng sản phẩm, vui lòng đọc kỹ</c><a https://www.iqiyi.com/user/register/protocol.html><c #00b909>“Thỏa thuận dịch vụ iQIYI”</c></a><c #ffffff>và</c><a https://privacy.iqiyi.com/policies><c #00b909>“Chính sách quyền riêng tư iQIYI”</c></a><c #ffffff>cùng tất cả điều khoản, đặc biệt là:</c><c #ffffff><n> </c>\r\n<c #ffffff><n>1. Các quy định về thu thập, lưu trữ, sử dụng, cung cấp cho bên ngoài và bảo vệ thông tin cá nhân, cùng các quyền của bạn;</c>\r\n<c #ffffff><n>2. Các điều khoản giới hạn trách nhiệm và miễn trừ trách nhiệm của chúng tôi;</c><c #ffffff><n>3. Những điều khoản quan trọng khác được đánh dấu bằng màu sắc hoặc chữ đậm.<n></c><c #ffffff><n> </c><c #ffffff><n>Nếu có thắc mắc về các thỏa thuận trên, bạn có thể liên hệ nhân viên hỗ trợ hoặc gửi email đến privacy＠qiyi.com. Khi nhấn “Đồng ý và tiếp tục”, bạn xác nhận đã đọc và đồng ý với toàn bộ nội dung các thỏa thuận trên.</c><c #ffffff><n> <n>Nếu đồng ý với các thỏa thuận trên, hãy nhấn “Đồng ý và tiếp tục” để bắt đầu sử dụng sản phẩm và dịch vụ!</c>"
};

  function cjkCount(s) {
    var m = String(s || "").match(/[\u3400-\u9fff]/g);
    return m ? m.length : 0;
  }

  // Chuỗi giống tiêu đề phim/series: còn chữ Hán sau khi bỏ mùa, số tập và nhãn phụ.
  // Tên phim phải được dịch trọn tên, không ghép từng chữ (古偶榜 -> "Cổ ngẫu" là lỗi).
  var TITLE_NOISE = /最新|热播|独播|自制|完结|连载|更新至|全\d+集|共\d+集|第\d+[集季部]|预告|花絮|看点|预告片|抢先|限免|会员|VIP|豆瓣|榜|No\.?\d+|\d+\s*(?:万|亿|次|人|分钟|分|年|月|日|集|季)/gi;
  // Verified against iq.com Vietnamese series records.
  var VERIFIED_TITLE_COPY = {"魅影神捕":"Mị Ảnh Thần Bộ", "田耕纪":"Điền Canh Kỷ", "逐玉":"Trục Ngọc"};
  var VERIFIED_ACTOR_COPY = {"曾舜晞":"Tăng Thuấn Hy", "田曦薇":"Điền Hi Vi"};
  function localizeTitleValue(value) {
    var raw = String(value || "");
    var episode = raw.match(/^(.*?)\s*第(\d+)集(?:\s+(.+))?$/);
    if (episode) {
      var sourceTitle = episode[1].trim();
      var result = (VERIFIED_TITLE_COPY[sourceTitle] || sourceTitle) + " · Tập " + episode[2];
      var subtitle = episode[3] && (FIXED_COPY[episode[3]] || episode[3]);
      return subtitle ? result + " · " + subtitle : result;
    }
    return FIXED_COPY[raw] || VERIFIED_TITLE_COPY[raw] || raw;
  }
  function looksLikeTitle(s) {
    var text = String(s || "");
    if (!cjkCount(text)) return false;
    var core = text.replace(TITLE_NOISE, "").replace(/[《》「」『』【】\[\]（）()·:：,，.。!！?？\s"“”]/g, "");
    return cjkCount(core) >= 2;
  }

  function internationalTitleId(value) {
    var id = String(value || "").trim();
    return /^\d{14,20}$/.test(id) || /^[A-Za-z0-9]{8,20}$/.test(id) ? id : "";
  }

  function titleIdFromUrl(value) {
    try {
      if (/^qips:\/\//i.test(String(value || ""))) {
        var nativeLink = String(value).replace(/^qips:\/\//i, "");
        var nativeAlbum = nativeLink.match(/(?:^|[;?&])albumid=(\d{8,24})(?=[;?&#]|$)/i);
        var nativeVideo = nativeLink.match(/(?:^|[;?&])tvid=(\d{8,24})(?=[;?&#]|$)/i);
        return nativeAlbum ? nativeAlbum[1] : nativeVideo ? nativeVideo[1] : "";
      }
      var url = new URL(value, location.href);
      var params = url.searchParams;
      var queryKeys = ["albumId", "albumid", "qipuId", "tvid", "tvId"];
      for (var i = 0; i < queryKeys.length; i++) {
        var found = internationalTitleId(params.get(queryKeys[i]));
        if (found) return found;
      }
      if (url.pathname === "/tvg/to_page_url" && /(^|\.)iqiyi\.com$/i.test(url.hostname)) {
        var encodedKeys = ["album_id", "tv_id"];
        for (var j = 0; j < encodedKeys.length; j++) {
          var encoded = params.get(encodedKeys[j]);
          if (!encoded) continue;
          try {
            var decoded = atob(encoded);
            if (/^\d{8,24}$/.test(decoded)) return decoded;
          } catch (e) {}
        }
      }
      var path = url.pathname.match(/(?:^|\/)(?:play|album)\/([A-Za-z0-9]{8,20})(?=\/|\.html|$)|\/(?:m|a|v)_([A-Za-z0-9]{8,20})(?=\.html|\/|$)/i);
      return path ? internationalTitleId(path[1] || path[2]) : "";
    } catch (e) { return ""; }
  }

  function isMovieTitleNode(node) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    for (var depth = 0; el && depth < 3; depth++, el = el.parentElement) {
      if (el.nodeType !== 1) continue;
      var label = String(el.className || "");
      // Search ranking badges share a parent with the title but are UI labels.
      if (depth === 0 && /(?:^|\s)search-board-item_tag(?:\s|$)/i.test(label)) return false;
      var entity = el.getAttribute("data-ai-entity") || "";
      var path = (el.ownerDocument && el.ownerDocument.location && el.ownerDocument.location.pathname) || location.pathname;
      if (el.tagName === "H1" && /(?:^|\/)(?:[va]_[^/]+|player(?:_mac)?)\.html$/i.test(path)) return true;
      if (/^(?:卡片|缩略图|影片|视频|专辑|剧集)标题$/.test(entity) || entity === "播放器标题栏视频标题" ||
          /filmFeed_title__|feedZaizhui_itemTitle__|thumbnailItemTitle|flexVideoList_title__|tilesItem_title__|videoListItem_title__|title_title__|meta_title(?:TextBlock|NotCloud)|search-board-item_title|(?:album|movie|video|player|detail)[-_]?(?:name|title)(?:__|\b)/i.test(label)) return true;
    }
    return false;
  }

  function nativeMovieTitleId(node) {
    if (!/^https:\/\/localwebapp\.iqiyi\.com(?:[:/]|$)/i.test(location.href)) return "";
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    if (!el) return "";
    // Native React cards use click handlers instead of links or data-ID attributes.
    var key = Object.keys(el).filter(function (name) { return name.indexOf("__reactFiber$") === 0; })[0];
    var fiber = key && el[key];
    for (var depth = 0; fiber && depth < 24; depth++, fiber = fiber.return) {
      var props = fiber.memoizedProps || {};
      var items = [props.item, props.data, props.originData, props.selectedData, props];
      for (var i = 0; i < items.length; i++) {
        var item = items[i];
        if (!item || typeof item !== "object" || Array.isArray(item)) continue;
        var id = internationalTitleId(item.albumId || item.album_id || item.albumid);
        if (id) return id;
        var link = titleIdFromUrl(item.play_url || item.playUrl || item.qipsUrl || item.page_url || item.url || "");
        if (link) return link;
        id = internationalTitleId(item.tvId || item.tvid || item.tv_id || item.entity_id);
        if (id) return id;
      }
    }
    return "";
  }

  function findInternationalTitleId(node) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    var attrs = ["data-albumid", "data-album-id", "data-qipuid", "data-qipu-id", "data-tvid", "data-tv-id"];
    var pageTitle = false, titleNode = false;
    for (var depth = 0; el && depth < 9; depth++) {
      if (el.nodeType === 1) {
        if (el.tagName === "BUTTON" || el.getAttribute("role") === "button") return "";
        var label = String(el.className || "") + " " + (el.id || "");
        if (depth < 3) {
          if (el.tagName === "TITLE" || el.tagName === "H1" || /(?:player|detail)[-_]?(?:name|title)|(?:name|title)[-_]?(?:player|detail)|meta_title(?:TextBlock|NotCloud)/i.test(label)) pageTitle = true;
          if (isMovieTitleNode(el) || pageTitle || /^H[1-6]$/.test(el.tagName) || /(?:^|[\s_-])(?:title|name)(?:Text|Main|Link|Label)?(?:[\s_-]|$)|(?:album|video|movie)[-_]?(?:name|title)|(?:name|title)[-_]?(?:album|video|movie)/i.test(label)) titleNode = true;
        }
        if (titleNode) {
          for (var i = 0; i < attrs.length; i++) {
            var found = internationalTitleId(el.getAttribute(attrs[i]));
            if (found) return found;
          }
        }
        if (el.tagName === "A") {
          // A movie link can also contain play buttons, descriptions and badges.
          if (!titleNode) return "";
          var fromLink = titleIdFromUrl(el.getAttribute("href") || "");
          if (fromLink) return fromLink;
        }
      }
      if (el.parentElement) el = el.parentElement;
      else {
        var tree = el.getRootNode && el.getRootNode();
        el = tree && tree.host ? tree.host : null;
      }
    }
    var pageDocument = node && node.ownerDocument;
    var pageUrl = (pageDocument && pageDocument.location && pageDocument.location.href) || location.href;
    return (titleNode && nativeMovieTitleId(node)) || (pageTitle ? titleIdFromUrl(pageUrl) : "");
  }

  function isActorNameNode(node) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    for (var depth = 0; el && depth < 3; depth++, el = el.parentElement) {
      if (el.nodeType !== 1) continue;
      var label = String(el.className || "");
      var entity = el.getAttribute("data-ai-entity") || "";
      if (/(?:演员|主演|明星|人物)(?:姓名|名称|名字)$/.test(entity) || /TVG演员筛选标签/.test(entity) ||
          /(?:act|actor|star|cast)[-_]?name(?:Text(?:Wrap)?|__|[-_]|\b)|(?:albumMeta|reserveMeta)OpenCastItem|(?:actor|cast)[-_]item[-_]name/i.test(label)) return true;
      if (el.tagName === "A" && /\/lib\/s_\d+\.html(?:[?#]|$)|\/actor-info\//i.test(el.getAttribute("href") || "")) return true;
    }
    return false;
  }

  function actorSourceText(node, value) {
    var raw = String(value || "");
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    if (!el) return raw;
    var key = Object.keys(el).filter(function (name) { return name.indexOf("__reactFiber$") === 0; })[0];
    var props = key && el[key] && el[key].memoizedProps;
    if (!props) return raw;
    if ((node.nodeType === 3 || el.textContent === raw) && typeof props.children === "string") return props.children;
    var attrs = ["title", "aria-label", "alt"];
    for (var i = 0; i < attrs.length; i++) {
      if (el.getAttribute(attrs[i]) === raw && typeof props[attrs[i]] === "string") return props[attrs[i]];
    }
    return raw;
  }

  function pumpIqcomMetadata() {
    while (!IQCOM_METADATA_STOPPED && IQCOM_METADATA_ACTIVE < 4 && IQCOM_METADATA_QUEUE.length) {
      (function (job) {
        IQCOM_METADATA_ACTIVE++;
        var controller = typeof AbortController === "function" ? new AbortController() : null;
        var timer = controller ? setTimeout(function () { controller.abort(); }, 45000) : null;
        if (controller) IQCOM_METADATA_CONTROLLERS.add(controller);
        var options = {headers:{"X-Iqiyi-Token":window.__iqiyiViToken || ""}, cache:"no-store"};
        if (controller) options.signal = controller.signal;
        Promise.resolve().then(function () {
          return fetch("http://127.0.0.1:18766/api/" + job.path, options);
        }).then(function (response) {
          return response.ok ? response.json() : Promise.reject(new Error("HTTP " + response.status));
        }).then(function (payload) {
          payload = payload || {};
          var retry = Number(payload.retryAfterMs) || 120000;
          job.entry.expires = Date.now() + (payload.title || payload.name ? 3600000 : Math.max(1000, Math.min(120000, retry)));
          job.resolve(payload);
        }, function () {
          job.entry.expires = Date.now() + 15000;
          job.resolve({});
        }).finally(function () {
          if (timer) clearTimeout(timer);
          if (controller) IQCOM_METADATA_CONTROLLERS.delete(controller);
          job.entry.pending = false;
          IQCOM_METADATA_ACTIVE--;
          pumpIqcomMetadata();
        });
      })(IQCOM_METADATA_QUEUE.shift());
    }
  }

  function requestIqcomMetadata(path) {
    var cached = IQCOM_METADATA_CACHE.get(path);
    if (cached && (cached.pending || cached.expires > Date.now())) return cached.promise;
    if (IQCOM_METADATA_STOPPED || IQCOM_METADATA_QUEUE.length >= 128) return Promise.resolve({});
    if (IQCOM_METADATA_CACHE.size >= 512) {
      for (var item of IQCOM_METADATA_CACHE) {
        if (!item[1].pending) { IQCOM_METADATA_CACHE.delete(item[0]); break; }
      }
    }
    var entry = {expires:0, pending:true};
    entry.promise = new Promise(function (resolve) {
      IQCOM_METADATA_QUEUE.push({path:path, entry:entry, resolve:resolve});
    });
    IQCOM_METADATA_CACHE.set(path, entry);
    pumpIqcomMetadata();
    return entry.promise;
  }

  function setMetadataPending(node, field, pending) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    // Keep cards and their controls visible; only mask the text label awaiting metadata.
    if (field || !el || el.nodeType !== 1 || el.tagName === "TITLE" || el.childElementCount) return;
    if (pending) {
      setUiAttribute(el, "data-iqiyi-vi-pending", "1");
      IQCOM_PENDING_LABELS.add(el);
    } else {
      el.removeAttribute("data-iqiyi-vi-pending");
      IQCOM_PENDING_LABELS.delete(el);
    }
  }

  function waitForIqcomMetadata(node, field, key, load, apply) {
    var slots = IQCOM_METADATA_WAITERS.get(node);
    if (!slots) { slots = {}; IQCOM_METADATA_WAITERS.set(node, slots); }
    field = field || "text";
    setMetadataPending(node, field === "text" ? "" : field, true);
    if (slots[field] && slots[field].key === key) return;
    var waiter = {key:key};
    slots[field] = waiter;
    Promise.resolve().then(load).then(function (payload) {
      if (!IQCOM_METADATA_STOPPED && node.isConnected !== false && slots[field] === waiter) apply(payload);
    }).finally(function () {
      if (slots[field] === waiter) {
        delete slots[field];
        setMetadataPending(node, field === "text" ? "" : field, false);
      }
    });
  }

  function requestInternationalActor(node, value, setter, field) {
    if (!isActorNameNode(node)) return false;
    var raw = String(value || "");
    var original = actorSourceText(node, raw);
    var source = original.replace(/^(\s*(?:主演|演员|导演)[：:\s]*)/, "");
    var names = source.match(/[\u3400-\u9fff]+(?:[·・][\u3400-\u9fff]+)*/g) || [];
    names = names.filter(function (name, index) { return names.indexOf(name) === index; });
    if (!names.length) return true;
    var token = window.__iqiyiViToken || "";
    var namesToFetch = names.filter(function (name) { return !VERIFIED_ACTOR_COPY[name]; });
    function applyVerifiedNames() {
      var translated = source.replace(/[\u3400-\u9fff]+(?:[·・][\u3400-\u9fff]+)*/g,
        function (name) { return VERIFIED_ACTOR_COPY[name] || name; });
      var result = tr(original.slice(0, original.length - source.length)) + translated;
      if (result === raw) return;
      if (setter) setter(result);
      else if (node && node.nodeType === 3 && node.isConnected && node.nodeValue === raw) node.nodeValue = result;
    }
    if (!namesToFetch.length || !token || !window.fetch) {
      setMetadataPending(node, field, !!(namesToFetch.length && window.__iqiyiViTokenPending));
      applyVerifiedNames();
      return true;
    }
    waitForIqcomMetadata(node, field, "actor:" + original + ":" + raw, function () {
      return Promise.all(namesToFetch.map(function (name) {
        return requestIqcomMetadata("international-actor?name=" + encodeURIComponent(name)).then(function (payload) {
          if (!payload || payload.sourceName !== name || typeof payload.name !== "string" || !payload.name.trim() || cjkCount(payload.name)) return null;
          return payload;
        });
      }));
    }, function (people) {
      if (!isActorNameNode(node) || actorSourceText(node, raw) !== original) return;
      // Replace complete names once, so a short name cannot corrupt another person's name.
      var result = source.replace(/[\u3400-\u9fff]+(?:[·・][\u3400-\u9fff]+)*/g, function (part) {
        var person = people.filter(function (person) { return person && person.sourceName === part; })[0];
        return person ? person.name : VERIFIED_ACTOR_COPY[part] || part;
      });
      // A profile heading can prefix the name with 演员 or 主演.
      var prefix = original.slice(0, original.length - source.length);
      result = tr(prefix) + result;
      if (result === raw) return;
      if (setter) setter(result);
      else if (node && node.nodeType === 3 && node.isConnected && node.nodeValue === raw) node.nodeValue = result;
    });
    return true;
  }

  function requestInternationalTitle(node, value, setter, field) {
    var raw = String(value || "");
    setMetadataPending(node, field, false);
    if (requestInternationalActor(node, value, setter, field)) return true;
    if (!/[\u3400-\u9fff]/.test(raw)) return false;
    var movieTitle = isMovieTitleNode(node);
    if (!looksLikeTitle(raw)) return movieTitle;
    var titleElement = node && node.nodeType === 3 ? node.parentElement : node;
    if (!movieTitle && (!titleElement || titleElement.tagName !== "TITLE")) return false;
    var titleContext = movieTitle || titleElement.tagName === "TITLE";
    var id = findInternationalTitleId(node);
    function setTitle(result) {
      result = FIXED_COPY[result] || localizeTitleValue(result);
      if (result === raw) return;
      if (setter) setter(result);
      else if (node && node.nodeType === 3 && node.isConnected && node.nodeValue === raw) node.nodeValue = result;
    }
    var prepared = localizeTitleValue(raw);
    var episodeTitle = raw.match(/^(.*?)\s*第\d+集/);
    if (prepared !== raw && (!cjkCount(prepared) || (episodeTitle && VERIFIED_TITLE_COPY[episodeTitle[1].trim()]))) {
      setTitle(prepared);
      return true;
    }
    if (!id) {
      if (titleContext) setTitle(raw);
      return titleContext;
    }

    function apply(payload) {
      var result = raw;
      if (findInternationalTitleId(node) === id && payload && payload.title && !cjkCount(payload.title)) {
        var source = payload.sourceTitle || "";
        var verifiedTitle = VERIFIED_TITLE_COPY[source];
        // Only replace the verified Chinese album name; keep unverified names intact.
        if (source && raw.indexOf(source) !== -1) result = raw.split(source).join(verifiedTitle || payload.title);
      }
      setTitle(result);
    }

    var token = window.__iqiyiViToken || "";
    if (!token || !window.fetch) {
      setMetadataPending(node, field, !!window.__iqiyiViTokenPending);
      apply({});
      return true;
    }
    waitForIqcomMetadata(node, field, "title:" + id + ":" + raw, function () {
      return requestIqcomMetadata("international-title?id=" + encodeURIComponent(id));
    }, apply);
    return true;
  }

  function trPatterns(s) {
    // Match the complete count before generic unit replacements consume 万/亿.
    s = s.replace(/(\d+(?:\.\d+)?)(万|亿)?(人正在看|次播放)/g, function (_, n, unit, kind) {
      var total = Number(n) * ({万:10000, 亿:100000000}[unit] || 1);
      var label = total >= 1000000 ? Number((total / 1000000).toFixed(2)) + " triệu" :
        total >= 1000 ? Number((total / 1000).toFixed(2)) + " nghìn" : String(total);
      return label + (kind === "人正在看" ? " người đang xem" : " lượt xem");
    });
    var count = "([0-9]+(?:\\.[0-9]+)?[wW万]?)";
    var templates = [
      [/^同时播放(\d+)台$/, "Phát đồng thời trên $1 thiết bị"],
      [/^(\d+)积分\/年$/, "$1 điểm/năm"],
      [/^(\d+)积分换$/, "Đổi bằng $1 điểm"],
      [new RegExp("^已兑换" + count + "件$"), "Đã đổi $1 lượt"],
      [/^用户(?=[@：:\s])(.*)$/, "Người dùng$1"],
      [/^年卡立省(\d+(?:\.\d+)?)元$/, "Gói năm tiết kiệm ngay $1 tệ"],
      [/^首月(\d+(?:\.\d+)?)元起$/, "Tháng đầu từ ¥$1"],
      [/^最低(\d+(?:\.\d+)?)折起$/, "Giá từ $1/10 giá gốc"],
      [/^超值价(\d+(?:\.\d+)?)元\/天起$/, "Chỉ từ $1 tệ/ngày"],
      [/^每月低至(\d+(?:\.\d+)?)元$/, "Chỉ từ $1 tệ/tháng"],
      [/^已优惠[¥￥](\d+(?:\.\d+)?)$/, "Đã tiết kiệm ¥$1"],
      [/^限时加赠(\d+)天$/, "Tặng thêm $1 ngày trong thời gian có hạn"],
      [/^次月续费(\d+(?:\.\d+)?)元$/, "Từ tháng sau gia hạn ¥$1"],
      [/^次季续费(\d+(?:\.\d+)?)元$/, "Từ quý sau gia hạn ¥$1"],
      [/^黄金会员首月低至(\d+(?:\.\d+)?)元$/, "VIP Vàng tháng đầu chỉ từ ¥$1"],
      [/^共(\d+)项$/, "Tổng cộng $1 quyền lợi"],
      [/^最高可得(\d+)天$/, "Nhận tối đa $1 ngày"],
      [/^花絮(\d+)$/, "Hậu trường $1"],
      [/^已失去(\d+)项特权$/, "Bạn đang bỏ lỡ $1 quyền lợi"],
      [/^开通会员享V(\d+)特权$/, "Đăng ký VIP để nhận quyền lợi V$1"],
      [/^会员更新至(\d+)集$/, "VIP đã cập nhật tới tập $1"],
      [/^查看全部[（(](\d+)[）)]$/, "Xem tất cả ($1)"],
      [/^(\d+)\s*部新片即将上映$/, "$1 phim mới sắp ra mắt"],
      [new RegExp("^" + count + "人已预约$"), "$1 người đã đặt nhắc"],
      [/^更新至(\d{2}-\d{2})期$/, "Cập nhật tới kỳ $1"],
      [/^本周([一二三四五六日天])更新$/, function (_, day) {
        return "Cập nhật " + ({一:"thứ Hai",二:"thứ Ba",三:"thứ Tư",四:"thứ Năm",五:"thứ Sáu",六:"thứ Bảy",日:"Chủ nhật",天:"Chủ nhật"})[day] + " tuần này";
      }],
      [/^热度破(\d+)$/, "Độ hot vượt $1"],
      [/^黄金年卡低至(\d+(?:\.\d+)?)折$/, "Gói VIP vàng năm còn $1/10 giá gốc"],
      [/^月月享(\d+(?:\.\d+)?)折$/, "Mỗi tháng còn $1/10 giá gốc"],
      [/^(\d+(?:\.\d+)?)折$/, "Còn $1/10 giá gốc"],
      [/^京ICP备(\d+)号$/, "Đăng ký ICP Bắc Kinh số $1"]
    ];
    for (var index = 0; index < templates.length; index++) {
      if (templates[index][0].test(s)) return s.replace(templates[index][0], templates[index][1]).replace(/([0-9.]+)[wW万]/g, "$1 vạn");
    }
    return s
      .replace(/展开\s*(\d+)\s*条回复/g, "$1 trả lời")
      .replace(/收起\s*(\d+)\s*条回复/g, "$1 trả lời")
      .replace(/展开\s*(\d+)\s*条/g, "$1")
      .replace(/(\d+)\s*条回复/g, "$1 trả lời")
      .replace(/更新至第(\d+)集/g, "Cập nhật tới tập $1")
      .replace(/彩蛋(\d+)/g, "Cảnh đặc biệt $1")
      .replace(/专访(\d+)/g, "Phỏng vấn $1")
      .replace(/共(\d+)部/g, "Tổng cộng $1 phim")
      .replace(/更新至(\d+)集/g, "Cập nhật tới tập $1")
      .replace(/更新至第(\d+)/g, "Cập nhật tới tập $1")
      .replace(/全(\d+)集/g, "$1 tập")
      .replace(/共(\d+)集/g, "$1 tập")
      .replace(/^第(\d+)集$/g, "Tập $1")
      .replace(/(\d+)集全/g, "$1 tập")
      .replace(/第(\d+)-(\d+)集/g, "Tập $1-$2")
      .replace(/限免第?(\d+)-(\d+)集/g, "Miễn phí tập $1-$2")
      .replace(/限免第?(\d+)集/g, "Miễn phí tập $1")
      .replace(/今日(\d{1,2}:\d{2})更新/g, "Cập nhật hôm nay lúc $1")
      .replace(/明日(\d{1,2}:\d{2})更新/g, "Cập nhật ngày mai lúc $1")
      .replace(/今日(\d{1,2}:\d{2})上线/g, "Phát hành hôm nay lúc $1")
      .replace(/明日(\d{1,2}:\d{2})上线/g, "Phát hành ngày mai lúc $1")
      .replace(/近(\d+)月上新/g, "Mới trong $1 tháng qua")
      .replace(/近(\d+)月转免/g, "Miễn phí trong $1 tháng qua")
      .replace(/近(\d+)周转免/g, "Miễn phí trong $1 tuần qua")
      .replace(/近(\d+)周上新/g, "Mới trong $1 tuần qua")
      .replace(/弹幕破(\d+(?:\.\d+)?)万/g, function (_, n) {
        var total = Number(n) * 10000;
        if (total >= 1000000) return "Bình luận vượt " + (total / 1000000).toFixed(total % 1000000 ? 1 : 0) + " triệu";
        return "Bình luận vượt " + (total / 1000).toFixed(total % 1000 ? 1 : 0) + " nghìn";
      })
      .replace(/(\d+(?:\.\d+)?)万/g, function (_, n) {
        var total = Number(n) * 10000;
        if (total >= 1000000) return (total / 1000000).toFixed(total % 1000000 ? 1 : 0) + " triệu";
        return (total / 1000).toFixed(total % 1000 ? 1 : 0) + " nghìn";
      })
      .replace(/(\d+) 部新片/g, "$1 phim mới")
      .replace(/(\d+) 部短剧/g, "$1 phim ngắn")
      .replace(/(\d{2}-\d{2})期/g, "Kỳ $1")
      .replace(/(\d+)分钟/g, "$1 phút")
      .replace(/(\d+(?:\.\d+)?)分(?!钟)/g, "$1 điểm")
      .replace(/(\d{4})年/g, "Năm $1")
      .replace(/观看至第(\d+)集/g, "Đã xem tới tập $1")
      .replace(/第(\d+)集/g, "Tập $1")
      .replace(/第(\d+)季/g, "Mùa $1")
      .replace(/总榜No\.(\d+)/g, " - BXH tổng số $1")
      .replace(/剧榜No\.(\d+)/g, " - BXH phim số $1")
      .replace(/榜No\.(\d+)/g, " - BXH số $1")
      .replace(/剧榜No\.(\d+)/g, " - BXH phim số $1")
      .replace(/短剧榜No\.(\d+)/g, " - BXH phim ngắn số $1")
      .replace(/最高热度破(\d+)/g, "Độ hot cao nhất vượt $1")
      .replace(/最高热度破万/g, "Độ hot cao nhất vượt 10 nghìn")
      .replace(/不看：/g, "Không xem: ")
      .replace(/(\d+)人正在看/g, "$1 người đang xem")
      .replace(/(\d+)次播放/g, "$1 lượt xem")
      .replace(/(\d+)分钟前/g, "$1 phút trước")
      .replace(/(\d+)小时前/g, "$1 giờ trước")
      .replace(/(\d+)天前/g, "$1 ngày trước")
      .replace(/(\d+)秒后可/g, "$1 giây nữa có thể ")
      .replace(/(\d+)秒后/g, "$1 giây nữa")
      .replace(/会员专享/g, "Độc quyền VIP")
      .replace(/用券解锁/g, "Mở bằng vé");
  }

  function tr(s) {
    if (!s) return s;
    var source = String(s);
    if (TEXT_CACHE.has(source)) return TEXT_CACHE.get(source);
    var translated = translateText(source);
    if (TEXT_CACHE.size >= 2000) TEXT_CACHE.delete(TEXT_CACHE.keys().next().value);
    TEXT_CACHE.set(source, translated);
    return translated;
  }

  function translateText(s) {
    var orig = String(s);
    var lead = orig.match(/^\s*/)[0];
    var tail = orig.match(/\s*$/)[0];
    var t = orig.slice(lead.length, orig.length - tail.length);
    if (!t) return orig;
    if (FIXED_COPY[t]) return lead + FIXED_COPY[t] + tail;
    if (VERIFIED_TITLE_COPY[t]) return lead + VERIFIED_TITLE_COPY[t] + tail;
    var wrapped = t.match(/^（(.+)）$/);
    if (wrapped && FIXED_COPY[wrapped[1]]) return lead + "(" + FIXED_COPY[wrapped[1]] + ")" + tail;
    var excluded = t.match(/^(?:不看[：:]|Không xem:)\s*(.+)$/);
    if (excluded && FIXED_COPY[excluded[1]]) return lead + "Không xem: " + FIXED_COPY[excluded[1]] + tail;
    var ranking = t.match(/^(.+?)(?:总榜|剧榜|榜)No\.(\d+)$/);
    if (ranking && FIXED_COPY[ranking[1]]) return lead + FIXED_COPY[ranking[1]] + " · BXH số " + ranking[2] + tail;
    var adSkipCountdown = t.match(/^(\d+)\s*秒后可跳过广告$/);
    if (adSkipCountdown) return lead + "Có thể bỏ qua quảng cáo sau " + adSkipCountdown[1] + " giây" + tail;
    var adCountdown = t.match(/^(\d+)\s*(?:s|秒)后可继续看正片$/i);
    if (adCountdown) return lead + "Sau " + adCountdown[1] + " giây có thể xem tiếp phim" + tail;
    var subtitleSwitch = t.match(/^已切换主字幕为\s*(.+)$/);
    if (subtitleSwitch) return lead + "Đã chuyển phụ đề chính sang " + tr(subtitleSwitch[1]) + tail;
    var adPrefix = t.match(/^广告\s+(.+)$/);
    if (adPrefix) return lead + "Quảng cáo " + adPrefix[1] + tail;
    // Most page text is already Vietnamese or English. Skip the dynamic Chinese templates for it.
    if (!/[\u3400-\u9fff]/.test(t)) return orig;

    var p = trPatterns(t);
    if (p !== t && !/[\u4e00-\u9fff]/.test(p)) return lead + p + tail;
    // A template must cover the complete Chinese phrase before replacing it.
    // 3. Chuỗi giống tiêu đề phim (còn chữ Hán sau khi bỏ nhãn như 榜/更新至/第N集) thì không được
    // ghép từng từ: giữ chữ Hán để engine dịch cả chuỗi thành một cụm đọc được.
    if (looksLikeTitle(t)) return lead + t + tail;
    return lead + t + tail;
  }

  function injectCSS() {
    if (!document.documentElement || document.getElementById("iqiyi-vi-css")) return;
    var s = document.createElement("style");
    s.id = "iqiyi-vi-css";
    s.textContent =
      '[data-iqiyi-vi-pending="1"]{visibility:hidden!important;}' +
      "#searchinput .search-placeholder{display:none!important}" +
      'img[src*="/watermark_rightTop"],img[src*="/watermark_rightBottom"]{display:none!important;}' +
      'html[lang="vi"] { overflow-wrap:normal; }' +
      'html[lang="vi"] [class*="tabName"],' +
      'html[lang="vi"] [class*="tagName"],' +
      'html[lang="vi"] [class*="tagHeader"],' +
      'html[lang="vi"] [class*="mainTabs"] span,' +
      'html[lang="vi"] [class*="comments_filter"],' +
      'html[lang="vi"] [class*="comments_replyBtn"],' +
      'html[lang="vi"] [class*="comments_expandBtn"],' +
      'html[lang="vi"] [class*="tabMenu_title"],' +
      'html[lang="vi"] [class*="tabMenu_tabItem"],' +
      'html[lang="vi"] [class*="side_item"],' +
      'html[lang="vi"] [class*="side_sideText"],' +
      'html[lang="vi"] [class*="filterTab"],' +
      'html[lang="vi"] [class*="sortTab"]{' +
      "white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis;word-break:keep-all;}" +
      'html[lang="vi"] [data-iqiyi-vi-fit="1"]{' +
      "white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;" +
      "overflow-wrap:normal!important;word-break:normal!important;}" +
      'html[lang="vi"] [class*="topbar_downloadClientBtn"]{min-width:64px!important;}' +
      'html[lang="vi"] #pcw_topbar{width:auto!important;flex-shrink:0!important;}' +
      'html[lang="vi"] #pcw_topbar>div{flex-shrink:0!important;}' +
      'html[lang="vi"] #pwaBtn{width:96px!important;flex:0 0 96px!important;}' +
      'html[lang="vi"] .pwaguide-entry-box{width:100%!important;min-width:0!important;box-sizing:border-box!important;align-items:center!important;}' +
      'html[lang="vi"] .pwaguide-entry-box-text{width:auto!important;white-space:nowrap!important;}' +
      'html[lang="vi"] [class*="side_sideText"]{' +
      'flex:1 1 0!important;min-width:0!important;width:auto!important;max-width:none!important;' +
      'white-space:normal!important;overflow:visible!important;text-overflow:clip!important;' +
      'overflow-wrap:normal!important;word-break:normal!important;line-height:18px!important;height:auto!important;font-size:13px!important;}' +
      'html[lang="vi"] [class*="side_leftBlock"],html[lang="vi"] [class*="side_activeLeftBlock"]{flex-shrink:0!important;}' +
      '#pcaSubtitleContainer,#pcaSubtitleContainer *,.caption-main,.caption-main *{' +
      'font-family:Arial,Helvetica,sans-serif!important;font-weight:700!important;color:#fff!important;' +
      '-webkit-text-stroke:0!important;' +
      'text-shadow:-1px -1px 0 #111,0 -1px 0 #111,1px -1px 0 #111,1px 0 0 #111,1px 1px 0 #111,0 1px 0 #111,-1px 1px 0 #111,-1px 0 0 #111!important;}' +
      '.caption-main::after,.caption-sub::after{content:none!important;}' +
      'video::cue{font-family:Arial,Helvetica,sans-serif;font-weight:700;color:#fff;background:transparent;' +
      '-webkit-text-stroke:0;text-shadow:-1px -1px 0 #111,0 -1px 0 #111,1px -1px 0 #111,1px 0 0 #111,1px 1px 0 #111,0 1px 0 #111,-1px 1px 0 #111,-1px 0 0 #111;}';
    (document.head || document.documentElement).appendChild(s);
  }

  function setUiAttribute(el, name, value) {
    if (el.getAttribute(name) !== value) el.setAttribute(name, value);
  }

  function isFixedUI(node) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    return !!(el && el.closest && el.closest("[data-iqiyi-vi-fixed]"));
  }

  function queryFixed(scope, selector) {
    scope = scope || document;
    var elements = [];
    if (scope.nodeType === 1 && scope.matches && scope.matches(selector)) elements.push(scope);
    if (scope.querySelectorAll) Array.prototype.push.apply(elements, scope.querySelectorAll(selector));
    return elements;
  }

  function hasFixedUI(scope) {
    if (!scope || !scope.querySelector) return false;
    if (scope.nodeType === 1 && scope.matches && scope.matches(FIXED_UI_TARGETS)) return true;
    return !!scope.querySelector(FIXED_UI_TARGETS);
  }

  function replaceFixedLabel(selector, label, scope) {
    queryFixed(scope, selector).forEach(function (el) {
      // Keep React's text node and all event handlers in place.
      if (el.childNodes.length !== 1 || el.firstChild.nodeType !== 3) return;
      if (el.firstChild.nodeValue !== label) el.firstChild.nodeValue = label;
      setUiAttribute(el, "data-iqiyi-vi-fixed", "1");
      setUiAttribute(el, "aria-label", label);
      setUiAttribute(el, "title", label);
    });
  }

  function replaceFixedBadge(imageId, label, width, background, color, height, scope) {
    height = height || 22;
    queryFixed(scope, 'img[src*="' + imageId + '"]').forEach(function (img) {
      var bounds = img.getBoundingClientRect ? img.getBoundingClientRect() : null;
      var badgeWidth = bounds && bounds.width > 0 ? bounds.width : width;
      var badgeHeight = bounds && bounds.height > 0 ? bounds.height : height;
      var fontSize = Math.min(11, badgeHeight * 0.75);
      var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + badgeWidth + '" height="' + badgeHeight + '" viewBox="0 0 ' + badgeWidth + ' ' + badgeHeight + '">' +
      '<rect width="100%" height="100%" rx="3" fill="' + background + '"/>' +
      '<text x="50%" y="50%" dy=".35em" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="' + fontSize + '" textLength="' + Math.min(badgeWidth - 2, label.length * fontSize * 0.58) + '" lengthAdjust="spacingAndGlyphs" font-weight="600" fill="' + color + '">' + label + '</text></svg>';
    var replacement = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
      setUiAttribute(img, "src", replacement);
      setUiAttribute(img, "alt", label);
      setUiAttribute(img, "title", label);
      setUiAttribute(img, "data-iqiyi-vi-fixed", "1");
      // Keep the component CSS dimensions, including tiny episode badges.
      img.style.maxWidth = "100%";
    });
  }

  function localizeFixedUI(scope) {
    scope = scope || document;
    // Prewritten Vietnamese labels are assigned by UI identity, never by text/dictionary lookup.
    replaceFixedLabel("#btn_gameBtn #text", "Game", scope);
    replaceFixedLabel("#clientBtn #text", "Ứng dụng", scope);
    replaceFixedLabel("#btn_msgBellBtn #text", "Tin nhắn", scope);
    replaceFixedLabel("#btn_historyBtn #text", "Lịch sử", scope);
    replaceFixedLabel("#btn_uploadBtn #text", "Tải lên", scope);
    replaceFixedLabel("#btn_vipBtnB #text", "Ưu đãi VIP", scope);
    replaceFixedLabel("#btn_vipBtnS #text", "VIP", scope);
    replaceFixedLabel("#pwaBtn .pwaguide-entry-box-text", "Truy cập nhanh", scope);
    replaceFixedLabel("#searchinput .search-button-filter-text", "Lọc", scope);
    replaceFixedLabel("#searchinput .search-button-text", "Tìm", scope);
    replaceFixedLabel("#userCenterSpan", "Trung tâm VIP", scope);
    queryFixed(scope, '#searchinput input[type="text"]').forEach(function (input) {
      setUiAttribute(input, "placeholder", "Tìm phim, diễn viên…");
      setUiAttribute(input, "aria-label", "Tìm phim, diễn viên");
    });
    queryFixed(scope, '[data-ai-entity="弹幕切换按钮,弹幕开关"]').forEach(function (button) {
      setUiAttribute(button, "aria-label", "Bật/tắt bình luận chạy");
      setUiAttribute(button, "title", "Bật/tắt bình luận chạy");
    });
    queryFixed(scope, '[data-ai-entity="弹幕设置按钮"]').forEach(function (button) {
      setUiAttribute(button, "aria-label", "Cài đặt bình luận chạy");
      setUiAttribute(button, "title", "Cài đặt bình luận chạy");
    });
    queryFixed(scope, '[data-ai-entity="弹幕输入框文本输入框"]').forEach(function (input) {
      setUiAttribute(input, "placeholder", "Gửi bình luận chạy thôi…");
      setUiAttribute(input, "aria-label", "Nội dung bình luận chạy");
    });
    function side(icon, label) {
      replaceFixedLabel('[class*="side_item"]:has(i[style*="' + icon + '"]) [class*="side_sideText"]', label, scope);
    }
    side("0fca556e9ff44373b9cc3def70478f7c", "Trang chủ");
    side("e97866bd36e543e3bbc879498c381492", "Theo dõi");
    side("a43328a04ad548ef9dea10279c7f25bf", "Video ngắn");
    side("82f48a4332754a9da53a7283cab83da5", "Phim ngắn");
    side("870c2806864c4d88af47ce4024fb040d", "Phim bộ");
    side("a8b88a5ce89a4fa796c376a75c22e609", "Phim điện ảnh");
    side("ce4137d9bcea43faac2974448512eae8", "Anime");
    side("a3a4e38a413e48379d793a3a34d750b7", "Giải trí");
    side("7c8a7660c57442dabe94a89650ad6e32", "Thiếu nhi");
    side("64f0bab27cb041da9be2a71c374dbce3", "Rạp trực tuyến");
    side("3bc17d55963b46ddb6bb3008a9f54c64", "Phim manga");
    side("aefa66bac405478087fa26723ea34d9d", "Phim tài liệu");
    side("f1a78f81b4af4d46ac01bb55bf537811", "Kiến thức");
    side("1cb01e9c9900455292092e9054f28400", "Tương tác");
    side("6ef0548415314aa4af94987f63705c69", "Game");
    side("3595e36cd72a45a7a3c08378b093a340", "Thể thao");
    side("bb8371b0b0c34883b697d82b496dfdb2", "Trực tiếp");
    side("fb2c5031e8864cee9a3d5ceaf6b9a56a", "Trailer phim mới");
    side("d788b03404d04d4a93f5dccda84069de", "Bảng xếp hạng");
    side("6651083568b44fc2b5e6525a4974bad6", "Cộng đồng");
    side("5ef3c7a727d1429f97d48ac45a95dbae", "Tiểu thuyết");
    side("all_ch.svg", "Mọi kênh");
    replaceFixedBadge("9013485acf0c4e07a2500429869d44f4", "Đang theo dõi", 82, "#b9ffe0", "#123d2c", 22, scope);
    replaceFixedBadge("5a2c3f02c5b54771b1047a27cc1f0447", "Miễn phí có hạn", 104, "#44cf98", "#123d2c", 22, scope);
    replaceFixedBadge("0b3bd1c78a4b4368b4e2da2fb206b5c8", "Miễn phí", 104, "#44cf98", "#123d2c", 22, scope);
    replaceFixedBadge("ac0bbaca7ffb4528a3a210b4078afbdf", "Miễn phí", 104, "#44cf98", "#123d2c", 22, scope);
    replaceFixedBadge("308107f863864cd8b364bc428f50f4ec", "VIP", 104, "#e5bd5f", "#453313", 22, scope);
    replaceFixedBadge("c4de74820c254b39ae0d692eef59f3a8", "VIP", 104, "#e5bd5f", "#453313", 22, scope);
    replaceFixedBadge("0db0e14b9886439098aa3cadf1b817ab", "Sắp chiếu", 104, "#4acbe7", "#123b4a", 22, scope);
    replaceFixedBadge("5205828ffa8f4fe3aef4e7b2c005148a", "Quảng cáo", 70, "#333333", "#ffffff", 22, scope);
    replaceFixedBadge("f660fb9c2f57476fbe234f397fd21e37", "Miễn phí", 48, "transparent", "#44cf98", 16, scope);
    // Channel IDs are part of the component class, not the film's title or synopsis.
    function channel(id, label) {
      var selector = '[class*="cardMemos_channelmark' + id + '__"]';
      queryFixed(scope, selector).forEach(function (el) {
        el.style.backgroundImage = "none";
        el.style.width = "auto";
        el.style.padding = "0 5px";
        el.style.backgroundColor = "#25282e";
        el.style.color = "#ffffff";
        el.style.font = "11px/22px Arial,Helvetica,sans-serif";
        if (!el.firstChild) el.appendChild(document.createTextNode(label));
      });
      replaceFixedLabel(selector, label, scope);
    }
    channel(1, "Phim điện ảnh");
    channel(2, "Phim bộ");
    channel(3, "Giải trí");
    channel(4, "Anime");
  }

  function translateDocumentTitle() {
    var title = document.querySelector("title");
    if (!title) return;
    var raw = title.textContent || "";
    if (title.firstChild && requestInternationalTitle(title.firstChild, raw, function (translated) {
      if ((title.textContent || "") === raw && title.firstChild && title.firstChild.nodeType === 3) title.firstChild.nodeValue = translated;
    })) return;
    var next = tr(raw);
    if (next !== raw && title.firstChild && title.firstChild.nodeType === 3) title.firstChild.nodeValue = next;
  }

  function fitCompact(node) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    if (!el || el.nodeType !== 1 || el.childElementCount) return;
    if (el.id === "pcaSubtitleContainer") return;
    // Hidden tooltips have zero width; forcing their overflow visible creates vertical text.
    if (el.clientWidth <= 0 || el.clientHeight <= 0) return;
    var text = (el.innerText || "").replace(/\s+/g, " ").trim();
    if (!text || text.length > 120) return;
    var fs = parseFloat((window.getComputedStyle(el).fontSize) || "12") || 12;
    var parent = el.parentElement;
    if (parent && parent.clientWidth > 0 && el.clientWidth > parent.clientWidth + 2) {
      el.style.maxWidth = "100%";
      el.style.boxSizing = "border-box";
    }
    if (el.clientHeight > 4 && el.clientHeight <= fs * 1.85 && el.scrollWidth <= el.clientWidth + 2) return;
    if (el.scrollHeight <= el.clientHeight + 2 && el.scrollWidth <= el.clientWidth + 2) return;
    setUiAttribute(el, "data-iqiyi-vi-fit", "1");
    el.style.whiteSpace = "nowrap";
    el.style.overflow = "hidden";
    var size = fs;
    while (size > 12 && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
      size -= 0.5;
      el.style.fontSize = size + "px";
    }
    if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) {
      el.style.overflowWrap = "normal";
      el.style.textOverflow = "ellipsis";
      if (!el.title) el.title = text;
    }
  }

  function walk(node) {
    if (!node || isFixedUI(node)) return;
    var parent = node.parentElement;
    for (; parent; parent = parent.parentElement) {
      if (SKIP[parent.tagName] || parent.tagName === "INPUT" || parent.tagName === "TEXTAREA" ||
          parent.isContentEditable || parent.id === "pcaSubtitleContainer" ||
          /subtitleContainer|caption-main|caption-sub/i.test(String(parent.className || "") + " " + parent.id)) return;
    }
    if (node.nodeType === 9 || node.nodeType === 11) {
      observeRoot(node);
      for (var childIndex = 0; childIndex < node.childNodes.length; childIndex++) walk(node.childNodes[childIndex]);
      return;
    }
    if (node.nodeType === 3) {
      var raw = node.nodeValue;
      if (requestInternationalTitle(node, raw, function (translated) {
        if (node.isConnected && node.nodeValue === raw) node.nodeValue = translated;
      })) return;
      var next = tr(raw);
      if (next !== raw) {
        node.nodeValue = next;
        if (!cjkCount(next)) fitCompact(node);
      }
      return;
    }
    if (node.nodeType !== 1 || SKIP[node.tagName] || node.id === "pcaSubtitleContainer" || /subtitleContainer|caption-main|caption-sub/i.test(String(node.className || "") + " " + node.id)) return;
    if (node.isContentEditable) return;
    if (node.shadowRoot) walk(node.shadowRoot);
    if (node.tagName === "IFRAME") {
      try {
        var frameDocument = node.contentDocument;
        if (frameDocument && frameDocument.documentElement) walk(frameDocument);
      } catch (e) {} // Cross-origin frames run their own extension content script.
    }
    if (node.tagName === "HTML" && /^zh(?:[-_]|$)/i.test(node.getAttribute("lang") || "")) setUiAttribute(node, "lang", "vi");
    ["title", "placeholder", "aria-label", "alt", "value"].forEach(function (a) {
      if (a === "value" && node.tagName !== "BUTTON" &&
          !(node.tagName === "INPUT" && /^(button|submit|reset)$/i.test(node.type || ""))) return;
      var v = node.getAttribute && node.getAttribute(a);
      if (!v && a === "value" && node.value) v = node.value;
      if (!v) return;
      if (requestInternationalTitle(node, v, function (translated) {
        if (node.getAttribute(a) === v) {
          if (a === "value" && "value" in node) node.value = translated;
          else setUiAttribute(node, a, translated);
        }
      }, a)) return;
      var n = tr(v);
      if (n !== v) {
        if (a === "value" && "value" in node) node.value = n;
        else setUiAttribute(node, a, n);
      }
    });
    if (node.tagName === "META" && /^(description|keywords)$/i.test(node.getAttribute("name") || "")) {
      var content = node.getAttribute("content");
      if (content) {
        var translatedContent = tr(content);
        if (translatedContent !== content) setUiAttribute(node, "content", translatedContent);
      }
    }
    if (node.tagName === "INPUT" || node.tagName === "TEXTAREA") return;
    var kids = node.childNodes;
    var hasEl = false;
    for (var i = 0; i < kids.length; i++) {
      if (kids[i].nodeType === 1) { hasEl = true; break; }
    }
    if (!hasEl && kids.length === 1 && kids[0].nodeType === 3) {
      var all = node.textContent;
      if (requestInternationalTitle(node, all, function (translated) {
        if (node.isConnected && node.childNodes.length === 1 && node.firstChild.nodeType === 3 && node.textContent === all) {
          node.firstChild.nodeValue = translated;
        }
      })) return;
      var t = tr(all);
      if (t !== all) {
        kids[0].nodeValue = t;
        if (!cjkCount(t)) fitCompact(node);
      }
      return;
    }
    for (var j = 0; j < kids.length; j++) walk(kids[j]);
  }

  var OBSERVED_ROOTS = new WeakSet();
  var ROOT_OBSERVERS = [];
  function observeRoot(root) {
    if (!root || OBSERVED_ROOTS.has(root) || typeof MutationObserver === "undefined") return;
    OBSERVED_ROOTS.add(root);
    var observer = new MutationObserver(handleMutations);
    observer.observe(root, { childList:true, subtree:true, characterData:true, attributes:true,
      attributeFilter:["title","placeholder","aria-label","alt","value","src"] });
    ROOT_OBSERVERS.push(observer);
  }

  function handleMutations(records) {
    if (IQCOM_METADATA_STOPPED) return;
    var changedNodes = new Set();
    var fixedScopes = new Set();
    function addFixedScope(node) {
      var el = node && node.nodeType === 3 ? node.parentElement : node;
      if (!el || el.nodeType !== 1) return;
      var target = el.closest(FIXED_UI_TARGETS);
      if (target) fixedScopes.add(target);
      else if (hasFixedUI(el)) fixedScopes.add(el);
    }
    (records || []).forEach(function (record) {
      if (record.type === "characterData") {
        changedNodes.add(record.target);
        addFixedScope(record.target);
      }
      else if (record.type === "childList") {
        addFixedScope(record.target);
        Array.prototype.forEach.call(record.addedNodes || [], function (node) {
          changedNodes.add(node);
          addFixedScope(node);
        });
      } else if (record.type === "attributes") {
        changedNodes.add(record.target);
        addFixedScope(record.target);
      }
    });
    // MutationObserver runs before paint, so changed labels can be localized in place.
    if (!document.getElementById("iqiyi-vi-css")) injectCSS();
    fixedScopes.forEach(localizeFixedUI);
    changedNodes.forEach(walk);
  }

  function scanLateShadowRoots() {
    var hosts = document.querySelectorAll("*");
    for (var i = 0; i < hosts.length; i++) {
      var root = hosts[i].shadowRoot;
      if (!root || OBSERVED_ROOTS.has(root)) continue;
      localizeFixedUI(root);
      walk(root);
    }
  }

  function run() {
    try {
      injectCSS();
      localizeFixedUI();
      translateDocumentTitle();
      document.querySelectorAll('[data-iqiyi-vi-fit="1"]').forEach(function (el) {
        if (!el.childElementCount) return;
        el.removeAttribute("data-iqiyi-vi-fit");
        if (String(el.className).indexOf("settingBtnAnchor") !== -1) el.removeAttribute("title");
        ["whiteSpace", "overflow", "overflowWrap", "fontSize", "textOverflow", "maxWidth", "boxSizing"].forEach(function (key) {
          el.style[key] = "";
        });
      });
      walk(document.documentElement || document.body);
    } catch (e) {}
  }

  window.__iqiyiVi = true;
  window.__iqiyiViVersion = ENGINE_VERSION;
  window.__iqiyiViReload = function () {
    TEXT_CACHE.clear();
    run();
  };

  // Observe the document itself: documentElement may not exist at document_start.
  observeRoot(document);
  run();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run, {once:true});
  // Mutations cover normal UI changes. Check for late attached shadow roots only once a
  // minute instead of rescanning and retranslating the full page every few seconds.
  var runTimer = setInterval(function () {
    if (!document.hidden) scanLateShadowRoots();
  }, 60000);
  window.__iqiyiViStop = function () {
    IQCOM_METADATA_STOPPED = true;
    IQCOM_PENDING_LABELS.forEach(function (el) { el.removeAttribute("data-iqiyi-vi-pending"); });
    IQCOM_PENDING_LABELS.clear();
    IQCOM_METADATA_CONTROLLERS.forEach(function (controller) { controller.abort(); });
    while (IQCOM_METADATA_QUEUE.length) IQCOM_METADATA_QUEUE.shift().resolve({});
    clearInterval(runTimer);
    document.removeEventListener("DOMContentLoaded", run);
    ROOT_OBSERVERS.forEach(function (observer) { observer.disconnect(); });
  };
})();
