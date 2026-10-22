"""Run: python -m unittest test_static_ui_copy"""
import json
from pathlib import Path
import re
import runpy
import unittest


class StaticUiCopyTests(unittest.TestCase):
    def test_fixed_copy_has_no_duplicate_keys(self):
        source = (Path(__file__).parent / "ui-engine.js").read_text(encoding="utf-8")
        match = re.search(r"var FIXED_COPY = (\{.*?\});", source, re.DOTALL)
        self.assertIsNotNone(match)
        pairs = json.loads(match.group(1), object_pairs_hook=list)
        keys = [key for key, _value in pairs]
        self.assertEqual(len(keys), len(set(keys)))
        titles_match = re.search(r"var VERIFIED_TITLE_COPY = (\{.*?\});", source)
        self.assertIsNotNone(titles_match)
        titles = json.loads(titles_match.group(1))
        self.assertFalse(set(keys) & set(titles), "Verified title translations should not be duplicated in FIXED_COPY")

    def test_player_menu_and_native_escaped_copy(self):
        module = runpy.run_path("apply-vi.py")
        copy = module["load_prepared_ui"]()
        expected = {
            "循环播放": "Phát lặp",
            "隔空手势": "Điều khiển bằng cử chỉ",
            "画面缩放": "Thu phóng hình ảnh",
            "原始尺寸": "Kích thước gốc",
            "常用快捷键": "Phím tắt thường dùng",
            "定时关机": "Hẹn giờ tắt máy",
            "播放问题诊断": "Chẩn đoán lỗi phát",
            "更多设置": "Cài đặt khác",
            "列表透明度": "Độ trong suốt danh sách",
            "歌词时间提前": "Hiển thị lời bài hát sớm hơn",
            "弹幕来一波…": "Gửi bình luận chạy thôi…",
            "弹幕走一波...": "Gửi bình luận chạy thôi...",
            "最多5个字符，回车可添加": "Tối đa 5 ký tự, nhấn Enter để thêm",
            "请输入": "Vui lòng nhập",
            "请输入密码": "Nhập mật khẩu",
            "请输入手机号": "Nhập số điện thoại",
            "请输入手机号/邮箱": "Nhập số điện thoại/email",
            "请输入验证码": "Nhập mã xác minh",
            "爱奇艺,客户端下载,下载": "iQIYI, tải ứng dụng, tải xuống",
            "爱奇艺客户端下载页面。": "Trang tải ứng dụng iQIYI.",
            "爱奇艺-在线视频网站-海量正版高清视频在线观看": "iQIYI – Xem video trực tuyến, kho nội dung bản quyền chất lượng cao",
            "爱奇艺-客户端下载": "Tải ứng dụng iQIYI",
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
            "为了更好处理您的反馈与建议，请填写QQ号/微信号": "Để hỗ trợ phản hồi của bạn tốt hơn, vui lòng nhập ID QQ hoặc WeChat.",
            "请填写意见建议": "Vui lòng nhập ý kiến góp ý.",
            "返回主窗口": "Trở về cửa sổ chính",
            "简体中文": "Tiếng Trung giản thể",
            "字幕大小": "Cỡ chữ phụ đề",
            "大": "Lớn",
            "特大": "Rất lớn",
            "字幕背景": "Nền phụ đề",
            "开启后，字幕将增加深色背景，浅色画面下更加清晰": "Bật để thêm nền tối cho phụ đề, giúp dễ đọc hơn trên nền sáng.",
            "使用字体：HarmonyOS_Sans_SC_Regular": "Phông chữ: HarmonyOS_Sans_SC_Regular",
            "清空搜索内容": "Xóa nội dung tìm kiếm",
            "已为您找到相关结果，问问AI快速总结重点": "Đã tìm thấy kết quả phù hợp. Hỏi AI để tóm tắt nhanh nội dung chính.",
            "问一问AI": "Hỏi AI",
            "立即播放": "Phát ngay",
            "筛选": "Lọc",
            "中剧": "Phim thời lượng vừa",
            "漫剧": "Phim hoạt họa truyện tranh",
            "枪战": "Đấu súng",
            "资费": "Hình thức xem",
            "近期转免": "Mới chuyển sang miễn phí",
            "免费解锁VIP": "Mở khóa nội dung VIP miễn phí",
            "反特谍战": "Phản gián - điệp chiến",
            "悬疑推理": "Trinh thám, bí ẩn",
            "家长里短": "Chuyện thường nhật trong gia đình",
            "科幻末世": "Khoa học viễn tưởng hậu tận thế",
            "都市日常": "Đời sống đô thị",
            "青春校园": "Thanh xuân học đường",
            "速看": "Xem nhanh",
            "详情": "Chi tiết",
            "加追": "Theo dõi",
            "开会员立享": "Đăng ký VIP, hưởng ưu đãi ngay",
            "长剧": "Phim dài tập",
            "短剧": "Phim ngắn",
            "精彩短视频": "Video ngắn nổi bật",
            "讨论": "Thảo luận",
            "二创": "Sáng tạo lại",
            "爆": "Bùng nổ",
            "热": "Đang hot",
            "预": "Sắp chiếu",
        }
        for source, translated in expected.items():
            self.assertEqual(copy[source], translated)
        xml = '<Option name="loop" text="循环播放" tooltip="常用快捷键"/>'
        patched, hits = module["patch_text"](xml, copy)
        self.assertEqual(hits, 2)
        self.assertEqual(patched, '<Option name="loop" text="Phát lặp" tooltip="Phím tắt thường dùng"/>')
        xml = '<Button tooptip="确定"/>'
        patched, hits = module["patch_text"](xml, copy)
        self.assertEqual(hits, 1)
        self.assertEqual(patched, '<Button tooptip="Xác nhận"/>')
        source = next(key for key in copy if key.startswith('<c #ffffff>感谢'))
        translated = copy[source]
        self.assertNotRegex(translated, r"[\u4e00-\u9fff]")
        self.assertIn("https://privacy.iqiyi.com/policies", translated)
        self.assertIn("privacy＠qiyi.com", translated)
        self.assertEqual(source.count("<"), translated.count("<"))
        from html import escape
        xml = '<Label text="' + escape(source, quote=True) + '"/>'
        patched, hits = module["patch_text"](xml, copy)
        self.assertEqual(hits, 1)
        self.assertIn(escape(translated, quote=True), patched)
        xml = '<TextField tip="弹幕来一波…" tooltip="发送弹幕"/>'
        patched, hits = module["patch_text"](xml, copy)
        self.assertEqual(hits, 2)
        self.assertEqual(patched, '<TextField tip="Gửi bình luận chạy thôi…" tooltip="Gửi bình luận chạy"/>')


if __name__ == "__main__":
    unittest.main()
