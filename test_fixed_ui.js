// Run with: node test_fixed_ui.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function element(text = "") {
  const el = {nodeType:1, tagName:"DIV", childNodes:[], style:{}, attrs:{},
    get childElementCount() {return this.childNodes.filter(node=>node.nodeType===1).length;},
    get textContent() {return this.childNodes.map(node=>node.nodeType===3?node.nodeValue:(node.textContent||"")).join("");},
    getAttribute(name) {return this.attrs[name] || null;},
    setAttribute(name, value) {this.attrs[name] = value;},
    closest() {return this.attrs["data-iqiyi-vi-fixed"] ? this : null;},
    appendChild(node) {this.childNodes.push(node);this.firstChild = this.childNodes[0];node.parentElement = this;}};
  if (text) el.appendChild({nodeType:3,nodeValue:text});
  return el;
}
const vip = element("会员特惠"), channel = element(), search = element();
const danmakuToggle = element(), danmakuSettings = element(), danmakuInput = element();
const searchBadgeGroup = element(), searchBadge = element("爆");
searchBadgeGroup.className = "search-board-item_title-group";
searchBadge.className = "search-board-item_tag pink";
searchBadgeGroup.appendChild(searchBadge);
danmakuInput.attrs.placeholder = "Chúng ta hãy vượt qua rào chắn...";
const following = element(), limited = element();
limited.getBoundingClientRect = () => ({width:28,height:12});
following.attrs.src = "https://example.test/9013485acf0c4e07a2500429869d44f4.svg";
limited.attrs.src = "https://example.test/5a2c3f02c5b54771b1047a27cc1f0447.svg";
const selectors = new Map([
  ["#userCenterSpan", [vip]],
  ['#searchinput input[type="text"]', [search]],
  ['[data-ai-entity="弹幕切换按钮,弹幕开关"]', [danmakuToggle]],
  ['[data-ai-entity="弹幕设置按钮"]', [danmakuSettings]],
  ['[data-ai-entity="弹幕输入框文本输入框"]', [danmakuInput]],
  ['[class*="cardMemos_channelmark2__"]', [channel]]
]);
const context = {
  window: {__iqiyiViDict:{"正片":"Sai", "旧标签":"Nhãn cũ"},__iqiyiViTitles:{"旧片名":"Tên cũ"}}, location:{pathname:"/",href:"https://www.iqiyi.com/"},
  localStorage:{length:0,getItem:()=>"{}"},
  document:{getElementById:()=>null,createTextNode:text=>({nodeType:3,nodeValue:text}),
    querySelectorAll(selector) {
      const match = selector.match(/^img\[src\*="([^"]+)"\]$/);
      return match ? [following, limited].filter(el=>el.attrs.src.includes(match[1])) : selectors.get(selector) || [];
    }},
  fetch:()=>assert.fail("Fixed labels must not call translation APIs")
};
let source = fs.readFileSync(__dirname + "/ui-engine.js", "utf8");
source = source.slice(0,source.indexOf("  function run()")) +
  "globalThis.localizeFixedUI=localizeFixedUI;globalThis.walk=walk;globalThis.tr=tr;globalThis.requestInternationalTitle=requestInternationalTitle;globalThis.localizeTitleValue=localizeTitleValue;})();";
vm.runInNewContext(source,context);
context.localizeFixedUI();
context.walk(searchBadgeGroup);
assert.equal(searchBadge.firstChild.nodeValue,"Bùng nổ","Translate ranking badges nested within movie-title groups");
assert.equal(vip.firstChild.nodeValue,"Trung tâm VIP");
assert.equal(search.attrs.placeholder,"Tìm phim, diễn viên…");
assert.equal(danmakuToggle.attrs["aria-label"],"Bật/tắt bình luận chạy");
assert.equal(danmakuToggle.attrs.title,"Bật/tắt bình luận chạy");
assert.equal(danmakuSettings.attrs["aria-label"],"Cài đặt bình luận chạy");
assert.equal(danmakuInput.attrs.placeholder,"Gửi bình luận chạy thôi…");
assert.equal(danmakuInput.attrs["aria-label"],"Nội dung bình luận chạy");
assert.equal(channel.firstChild.nodeValue,"Phim bộ");
assert.equal(channel.style.backgroundImage,"none");
assert.equal(following.attrs.alt,"Đang theo dõi");
assert.equal(limited.attrs.alt,"Miễn phí có hạn");
assert.match(decodeURIComponent(limited.attrs.src), /width="28" height="12"/);
assert.equal(limited.style.width,undefined);
assert.equal(limited.style.height,undefined);
assert.equal(context.tr("正片"),"Tập chính");
assert.equal(context.tr("专访"),"Phỏng vấn");
assert.equal(context.tr("逐玉"),"Trục Ngọc","Resolve verified titles through the title table without a duplicate copy entry");

assert.equal(context.window.__iqiyiViAutoStatus,undefined,"No UI translation status shim remains");
assert.match(decodeURIComponent(following.attrs.src),/>Đang theo dõi<\/text>/);
assert.equal(following.attrs.src.includes("example.test"),false);
// Fixed labels and their attributes bypass the generic dictionary walker.
context.walk(vip);
assert.equal(vip.firstChild.nodeValue,"Trung tâm VIP");
const originalNode = vip.firstChild;
context.localizeFixedUI();
assert.equal(vip.firstChild,originalNode);
assert.equal(channel.childNodes.length,1);
// React can reuse a badge image for a different permission state.
following.attrs.src = "https://example.test/5a2c3f02c5b54771b1047a27cc1f0447.svg";
context.localizeFixedUI();
assert.equal(following.attrs.alt,"Miễn phí có hạn");
console.log("Fixed Vietnamese labels and badge replacement checks passed.");

for (const [source, expected] of [
  ["会员特惠，新人专享","Ưu đãi VIP dành cho khách mới"],
  ["同时播放1台","Phát đồng thời trên 1 thiết bị"],
  ["已兑换4.2w件","Đã đổi 4.2 vạn lượt"],
  ["首月1分钱","Tháng đầu 0,01 tệ"],
  ["本周二更新","Cập nhật thứ Ba tuần này"],
  ["古装探案榜No.9","Phá án cổ trang · BXH số 9"],
  ["不看：古装爱情","Không xem: Tình cảm cổ trang"],
  ["256部新片即将上映","256 phim mới sắp ra mắt"],
  ["综艺榜","BXH giải trí"],
  ["动漫榜","BXH anime"],
  ["未知电影名字","未知电影名字"]
]) assert.equal(context.tr(source),expected,source);
assert.equal(context.tr("未知1分钱"),"未知1分钱", "No partial template translation");
console.log("Observed VIP/homepage phrases, complete templates and unknown-text checks passed.");

assert.equal(context.tr("旧标签"),"旧标签","Legacy UI dictionaries must be ignored");
assert.equal(context.tr("旧片名"),"旧片名","Legacy film title tables must be ignored");
assert.equal(context.window.__iqiyiViDict["正片"],"Sai","Legacy dictionaries are ignored without runtime cleanup code");
assert.equal(context.window.__iqiyiViTitles["旧片名"],"Tên cũ","Legacy title dictionaries are ignored without runtime cleanup code");
assert.equal(context.tr("已切换主字幕为 Tiếng Việt iq.com"),"Đã chuyển phụ đề chính sang Tiếng Việt iq.com");
assert.equal(context.tr("已切换主字幕为"),"Đã chuyển phụ đề chính sang ","Translate the split player-toast prefix and preserve a separator");
assert.equal(context.tr("已切换主字幕为 简体中文"),"Đã chuyển phụ đề chính sang 简体中文","Keep dynamic track names intact");
const splitToast = element();
splitToast.appendChild(element("已切换主字幕为"));
splitToast.appendChild(element("Tiếng Việt iq.com"));
context.walk(splitToast);
assert.equal(splitToast.childNodes[0].firstChild.nodeValue,"Đã chuyển phụ đề chính sang ","Translate the actual split toast prefix node");
assert.equal(splitToast.childNodes[1].firstChild.nodeValue,"Tiếng Việt iq.com","Keep the selected track label intact");
assert.equal(context.tr("分集视频标题"),"Hiển thị tiêu đề tập phim");
assert.equal(context.tr("天才医生跌落神坛，小城行医暖人心"),"Bác sĩ thiên tài sa cơ, hành nghề ở thị trấn nhỏ, sưởi ấm lòng người");
assert.equal(context.tr("（仅针对1080P及以下清晰度生效）"),"(Chỉ áp dụng cho chất lượng 1080P trở xuống)");
assert.equal(context.tr("长按倍速"),"Nhấn giữ để tăng tốc");
const nestedSettingsCopy = [
  ["铺满（保持比例）", "Lấp đầy (giữ nguyên tỷ lệ)"],
  ["铺满（拉伸画面）", "Lấp đầy (kéo giãn khung hình)"],
  ["老板键", "Phím ẩn nhanh"],
  ["全屏/退出全屏", "Toàn màn hình/Thoát toàn màn hình"],
  ["Alt + 回车", "Alt + Enter"],
  ["播放/暂停", "Phát/Tạm dừng"],
  ["空格", "Phím cách"],
  ["快进（长按开启倍速）", "Tua nhanh (nhấn giữ để tăng tốc)"],
  ["快退", "Tua lùi"],
  ["增加音量", "Tăng âm lượng"],
  ["降低音量", "Giảm âm lượng"],
  ["全部快捷键", "Tất cả phím tắt"]
];
const nestedSettings = element();
for (const [source] of nestedSettingsCopy) nestedSettings.appendChild(element(source));
context.walk(nestedSettings);
assert.deepEqual(nestedSettings.childNodes.map(node=>node.firstChild.nodeValue),
  nestedSettingsCopy.map(([, expected])=>expected), "Translate nested player settings and shortcut pages");
assert.equal(context.tr("点击一下，快速跳过广告"),"Nhấn một lần để bỏ qua quảng cáo");
assert.equal(context.tr("▶ 跳过广告观看正片"),"▶ Bỏ qua quảng cáo để xem phim");
assert.equal(context.tr("关闭广告，放大暂停画面"),"Đóng quảng cáo để phóng to khung hình khi tạm dừng");
assert.equal(context.tr("跳过广告"),"Bỏ qua quảng cáo");
assert.equal(context.tr("关闭此广告"),"Tắt quảng cáo này");
assert.equal(context.tr("首月12元起"),"Tháng đầu từ ¥12");
assert.equal(context.tr("免费集将看完"),"Sắp hết số tập được xem miễn phí");
assert.equal(context.tr("开会员看全集"),"Đăng ký VIP để xem trọn bộ");
assert.equal(context.tr("5s后可继续看正片"),"Sau 5 giây có thể xem tiếp phim");
assert.equal(context.tr("19秒后可继续看正片"),"Sau 19 giây có thể xem tiếp phim");
assert.equal(context.tr("了解详情"),"Xem chi tiết");
assert.equal(context.tr("打开广告落地页"),"Mở trang quảng cáo");
assert.equal(context.tr("广告 微粒贷"),"Quảng cáo 微粒贷","Translate the ad label and retain the product name");
assert.equal(context.tr("会员更新至30集"),"VIP đã cập nhật tới tập 30");
assert.equal(context.tr("查看全部(30)"),"Xem tất cả (30)");
assert.equal(context.tr("弹幕走一波..."),"Gửi bình luận chạy thôi...");
assert.equal(context.localizeTitleValue("魅影神捕 第2集"),"Mị Ảnh Thần Bộ · Tập 2");
assert.equal(context.localizeTitleValue("未确认剧名 第2集"),"未确认剧名 · Tập 2","Keep unverified names intact");
assert.equal(context.localizeTitleValue("田耕纪"),"Điền Canh Kỷ","Use the verified Vietnamese iq.com title");
assert.equal(context.localizeTitleValue("逐玉 第2集"),"Trục Ngọc · Tập 2","Use verified Vietnamese title for the current player header");
assert.equal(context.tr("Truc Ngoc"),"Trục Ngọc","Preserve the official title's Vietnamese diacritics");
assert.equal(context.localizeTitleValue("田耕纪 第22集 沈诺蔓儿制定救人计划"),
  "Điền Canh Kỷ · Tập 22 · Thẩm Nặc và Liên Mạn Nhi lập kế hoạch cứu người");
assert.equal(context.tr("客户端4K播放"),"Phát 4K trên ứng dụng");
assert.equal(context.tr("黄金关闭此广告"),"VIP Vàng có thể tắt quảng cáo");
assert.equal(context.tr("7秒后可跳过广告"),"Có thể bỏ qua quảng cáo sau 7 giây");
assert.equal(context.tr("新婚当晚被关柴房！她被养兄长骗嫁为妾"),
  "Đêm tân hôn bị nhốt trong nhà củi! Nàng bị anh nuôi lừa gả làm thiếp");
assert.equal(context.tr("《田耕纪》腹黑大姐连花儿，嫁人了也不安..."),
  "Chị cả Liên Hoa mưu mô trong “Điền Canh Kỷ”, lấy chồng rồi vẫn chưa yên...");
assert.equal(context.tr("爱奇艺-客户端下载"),"Tải ứng dụng iQIYI");
assert.equal(context.tr("404错误页页"),"Trang lỗi 404");
assert.equal(context.tr("Internet Explorer 无法显示该网页"),"Internet Explorer không thể hiển thị trang này.");
assert.equal(context.tr("您可以尝试以下操作:"),"Bạn có thể thử những cách sau:");
assert.equal(context.tr("若您已经连接到Internet，请重新"),"Nếu bạn đã kết nối Internet, hãy");
assert.equal(context.tr("简体中文"),"Tiếng Trung giản thể");
assert.equal(context.tr("字幕大小"),"Cỡ chữ phụ đề");
assert.equal(context.tr("标准"),"Chuẩn");
assert.equal(context.tr("大"),"Lớn");
assert.equal(context.tr("特大"),"Rất lớn");
assert.equal(context.tr("字幕背景"),"Nền phụ đề");
assert.equal(context.tr("开启后，字幕将增加深色背景，浅色画面下更加清晰"),"Bật để thêm nền tối cho phụ đề, giúp dễ đọc hơn trên nền sáng.");
assert.equal(context.tr("使用字体：HarmonyOS_Sans_SC_Regular"),"Phông chữ: HarmonyOS_Sans_SC_Regular");
assert.equal(context.tr("正在看："),"Đang xem:");
assert.equal(context.tr("刷新页面"),"Làm mới trang");
assert.equal(context.tr("关注"),"Theo dõi");
assert.equal(context.tr("互动"),"Tương tác");
assert.equal(context.tr("清空搜索内容"),"Xóa nội dung tìm kiếm");
assert.equal(context.tr("已为您找到相关结果，问问AI快速总结重点"),"Đã tìm thấy kết quả phù hợp. Hỏi AI để tóm tắt nhanh nội dung chính.");
assert.equal(context.tr("问一问AI"),"Hỏi AI");
assert.equal(context.tr("综合"),"Tổng hợp");
assert.equal(context.tr("用户"),"Người dùng");
assert.equal(context.tr("立即播放"),"Phát ngay");
assert.equal(context.tr("大家还爱看"),"Mọi người cũng thích xem");
assert.equal(context.tr("相关短视频"),"Video ngắn liên quan");
assert.equal(context.tr("卫视"),"Kênh truyền hình vệ tinh");
assert.equal(context.tr("都市爱情"),"Tình yêu đô thị");
assert.equal(context.tr("内地"),"Trung Quốc đại lục");
assert.equal(context.tr("今日更新"),"Cập nhật hôm nay");
assert.equal(context.tr("彩蛋1"),"Cảnh đặc biệt 1");
assert.equal(context.tr("专访2"),"Phỏng vấn 2");
assert.equal(context.tr("共100部"),"Tổng cộng 100 phim");
for (const [source, expected] of [
  ["筛选", "Lọc"], ["中剧", "Phim thời lượng vừa"], ["少儿", "Thiếu nhi"],
  ["漫剧", "Phim hoạt họa truyện tranh"], ["枪战", "Đấu súng"],
  ["时间", "Thời gian"], ["资费", "Hình thức xem"],
  ["近期转免", "Mới chuyển sang miễn phí"], ["免费解锁VIP", "Mở khóa nội dung VIP miễn phí"],
  ["10年代", "Thập niên 2010"], ["00年代", "Thập niên 2000"],
  ["共100部", "Tổng cộng 100 phim"], ["近1周转免", "Miễn phí trong 1 tuần qua"],
  ["反特谍战", "Phản gián - điệp chiến"], ["悬疑推理", "Trinh thám, bí ẩn"],
  ["家庭伦理", "Tâm lý gia đình"], ["总裁", "Tổng tài"], ["穿越", "Xuyên không"],
  ["战神归来", "Chiến thần trở lại"]
]) assert.equal(context.tr(source),expected,source);

for (const [source, expected] of [
  ["通知", "Thông báo"], ["点赞", "Lượt thích"], ["在追", "Đang theo dõi"],
  ["用户@sample123", "Người dùng@sample123"],
  ["钱包", "Ví tiền"], ["关闭验证", "Đóng xác minh"],
  ["刷新验证", "Làm mới xác minh"], ["请输入您听到的内容", "Nhập nội dung bạn nghe được"],
  ["热搜", "Tìm kiếm nổi bật"], ["热点", "Chủ đề nóng"], ["搜索推荐", "Đề xuất tìm kiếm"],
  ["选择不考虑观看的原因：", "Chọn lý do bạn không muốn xem:"],
  ["选择不考虑观看的原因:", "Chọn lý do bạn không muốn xem:"],
  ["已看过", "Đã xem"], ["重复推荐", "Được đề xuất nhiều lần"],
  ["就是不想看", "Tôi không muốn xem"], ["上传", "Tải lên"],
  ["甜宠", "Ngọt sủng"], ["暗恋成真", "Thầm yêu thành đôi"], ["打脸虐渣", "Vả mặt kẻ xấu"],
  ["现代言情", "Ngôn tình hiện đại"], ["闪婚", "Cưới chớp nhoáng"],
  ["虐恋", "Tình yêu ngược"], ["破镜重圆", "Gương vỡ lại lành"],
  ["先婚后爱", "Cưới trước, yêu sau"], ["东方玄幻", "Huyền huyễn phương Đông"],
  ["恋爱", "Tình yêu"], ["恋爱脑", "Lụy tình"], ["百姓趣闻", "Chuyện đời thường thú vị"],
  ["农村", "Nông thôn"], ["御兽", "Ngự thú"], ["废柴", "Phế vật"],
  ["迷雾剧场", "Rạp Sương Mù"], ["大家剧场", "Rạp Phim Đại Chúng"],
  ["恋恋剧场", "Rạp Phim Tình Cảm"], ["小逗剧场", "Rạp Hài"],
  ["画质", "Chất lượng hình ảnh"], ["超高清4K", "Siêu nét 4K"],
  ["准高清", "Gần HD"], ["查看全部内容", "Xem toàn bộ nội dung"],
  ["风云榜总榜", "Bảng xếp hạng tổng hợp"], ["查看完整风云榜", "Xem đầy đủ bảng xếp hạng"],
  ["智能", "Thông minh"], ["自动调节画质", "Tự động điều chỉnh chất lượng hình ảnh"],
  ["音效", "Hiệu ứng âm thanh"], ["本剧全集免费看", "Xem miễn phí toàn bộ phim này"],
  ["番外", "Ngoại truyện"], ["分", "điểm"],
  ["试看已结束，继续观看请开通VIP会员", "Đã hết thời gian xem thử. Đăng ký VIP để xem tiếp."],
  ["未开通会员，不能观看海量VIP内容", "Bạn chưa đăng ký VIP nên chưa xem được kho nội dung VIP."],
  ["黄金VIP", "VIP Vàng"], ["白金VIP", "VIP Bạch Kim"], ["星钻VIP", "VIP Kim Cương"],
  ["连续包年", "Gia hạn tự động hằng năm"], ["赠送以下权益", "Quyền lợi được tặng kèm"],
  ["会员特权对比", "So sánh quyền lợi VIP"], ["会员抢先看", "Xem trước nội dung VIP"],
  ["本页展示的划线价为建议零售价", "Giá gạch ngang trên trang là giá bán lẻ đề xuất."],
  ["《会员协议》", "“Thỏa thuận hội viên”"]
]) assert.equal(context.tr(source), expected, source);
for (const [source, expected] of [
  ["已优惠¥100", "Đã tiết kiệm ¥100"],
  ["限时加赠15天", "Tặng thêm 15 ngày trong thời gian có hạn"],
  ["次月续费25元", "Từ tháng sau gia hạn ¥25"],
  ["次季续费68元", "Từ quý sau gia hạn ¥68"],
  ["黄金会员首月低至12元", "VIP Vàng tháng đầu chỉ từ ¥12"],
  ["共3项", "Tổng cộng 3 quyền lợi"], ["花絮3", "Hậu trường 3"]
]) assert.equal(context.tr(source), expected, source);

const libraryTitle = element("未知电影名字");
libraryTitle.className = "tilesItem_title__test";
libraryTitle.getRootNode = () => ({host:null});
assert.equal(context.requestInternationalTitle(libraryTitle.firstChild, libraryTitle.firstChild.nodeValue,
  value => {assert.equal(value,"未知电影名字");}),true,"Recognize native home and library movie cards");
const verifiedTitleCard = element("魅影神捕 第2集");
verifiedTitleCard.className = "title_title__test";
verifiedTitleCard.getRootNode = () => ({host:null});
let verifiedCardTitle = "";
assert.equal(context.requestInternationalTitle(verifiedTitleCard.firstChild, verifiedTitleCard.firstChild.nodeValue,
  value => {verifiedCardTitle = value;}),true);
assert.equal(verifiedCardTitle,"Mị Ảnh Thần Bộ · Tập 2","Translate verified native player header title without an entity hint");

const movieTitle = element("魅影神捕 第2集");
movieTitle.tagName = "SPAN";
movieTitle.className = "title_title__0ccLD";
movieTitle.attrs["data-ai-entity"] = "播放器标题栏视频标题";
movieTitle.getRootNode = () => ({host:null});
let localizedMovieTitle = "";
assert.equal(context.requestInternationalTitle(movieTitle.firstChild, movieTitle.firstChild.nodeValue,
  value => {localizedMovieTitle = value;}),true);
assert.equal(localizedMovieTitle,"Mị Ảnh Thần Bộ · Tập 2","Use verified title copy and translate the episode suffix");
const pageTitle = element("爱奇艺-客户端下载");
pageTitle.tagName = "TITLE";
pageTitle.getRootNode = () => ({host:null});
let localizedPageTitle = "";
assert.equal(context.requestInternationalTitle(pageTitle.firstChild, pageTitle.firstChild.nodeValue,
  value => {localizedPageTitle = value;}),true);
assert.equal(localizedPageTitle,"Tải ứng dụng iQIYI","Translate the fixed document title");
