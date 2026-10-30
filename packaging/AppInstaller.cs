using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class AppInstaller
{
    private const string Version = "__VERSION__";
    private const string RegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\IQIYI-VI";
    private const string RunPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string Manifest = ".installed-files.json";
    private static string Root = InstalledRoot() ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "IQIYI-VI");
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    private static string InstalledRoot()
    {
        using (var key = Registry.CurrentUser.OpenSubKey(RegistryPath))
            return key == null ? null : key.GetValue("InstallLocation") as string;
    }

    internal static string NormalizeRoot(string path)
    {
        if (String.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path) || path.StartsWith(@"\\") || path.Length < 3 || path[1] != ':' || (path[2] != '\\' && path[2] != '/'))
            throw new InvalidDataException("Chọn đường dẫn đầy đủ trên ổ đĩa, ví dụ D:\\Apps\\IQIYI-VI.");
        string root = Path.GetFullPath(path).TrimEnd('\\', '/');
        if (root.Length <= 3 || root.IndexOfAny(new[] { '*', '?', '"', '<', '>', '|' }) >= 0 || root.Substring(2).Contains(':'))
            throw new InvalidDataException("Chọn thư mục riêng cho ứng dụng, không chọn thư mục gốc ổ đĩa.");
        for (var directory = new DirectoryInfo(root); directory != null; directory = directory.Parent)
            if (directory.Exists && (directory.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Chọn thư mục thật, không dùng liên kết thư mục.");
        return root;
    }

    internal static string UninstallRoot(string path, string registered)
    {
        string root = NormalizeRoot(path);
        if (registered == null || !String.Equals(root, NormalizeRoot(registered), StringComparison.OrdinalIgnoreCase) || !File.Exists(Path.Combine(root, Manifest)))
            throw new InvalidDataException("Chạy Gỡ cài đặt từ thư mục app đã đăng ký với Windows.");
        return root;
    }

    [STAThread]
    private static int Main(string[] args)
    {
        using (var mutex = new Mutex(false, @"Local\IQIYI-VI-Setup"))
        {
            bool owned;
            try { owned = mutex.WaitOne(TimeSpan.FromSeconds(10)); }
            catch (AbandonedMutexException) { owned = true; }
            if (!owned) return 1;
            try { return Run(args); }
            finally { mutex.ReleaseMutex(); }
        }
    }

    private static int Run(string[] args)
    {
        Application.EnableVisualStyles();
        try
        {
#if UNINSTALLER
            if (args.Length == 2 && args[0] == "--remove")
            {
                // The helper is copied outside the app so Windows can remove Uninstall.exe.
                Root = UninstallRoot(args[1], InstalledRoot());
                ShowWindow(true);
                return 0;
            }
            if (args.Length != 0)
                throw new InvalidDataException("Chạy Gỡ cài đặt từ thư mục app đã cài.");
            Root = UninstallRoot(AppDomain.CurrentDomain.BaseDirectory, InstalledRoot());
            string helper = Path.Combine(Path.GetTempPath(), "IQIYI-VI-Uninstall-" + Guid.NewGuid().ToString("N") + ".exe");
            File.Copy(Assembly.GetExecutingAssembly().Location, helper);
            Process.Start(new ProcessStartInfo(helper, "--remove " + Quote(Root)) { UseShellExecute = false });
#else
            if (args.Length == 2 && args[0] == "--check-package")
            {
                string stage = NewStage();
                try
                {
                    ExtractPackage(stage);
                    RunPython(stage, "--check");
                    File.WriteAllText(args[1], Json.Serialize(new { ok = true, version = Version, files = ReadManifest(stage).Length }));
                }
                finally { DeleteStage(stage); }
                return 0;
            }
            if (args.Length != 0) throw new ArgumentException("Tham số không hợp lệ.");
            ShowWindow(false);
#endif
            return 0;
        }
        catch (Exception error)
        {
            if (args.Length == 2 && args[0] == "--check-package")
            {
                File.WriteAllText(args[1], Json.Serialize(new { ok = false, error = error.Message }));
                return 1;
            }
            MessageBox.Show(error.Message, "iQIYI – Quản lý phụ đề", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static void ShowWindow(bool uninstall)
    {
        using (var form = new Form { Text = uninstall ? "Gỡ iQIYI – Quản lý phụ đề" : "Cài iQIYI – Quản lý phụ đề", ClientSize = new Size(620, 465), AutoScaleMode = AutoScaleMode.Dpi, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, StartPosition = FormStartPosition.CenterScreen, Font = new Font("Segoe UI", 10) })
        {
            var title = new Label { Text = "iQIYI – Quản lý phụ đề " + Version, AutoSize = true, Location = new Point(24, 24), Font = new Font("Segoe UI", 15, FontStyle.Bold) };
            var detail = new Label { Text = uninstall ? "Gỡ ứng dụng và biểu tượng mở app.\nThư viện, phiên đăng nhập và tiến độ dịch được giữ lại.\n" + Root : "Cài cho tài khoản Windows hiện tại, kèm Python và tiện ích trình duyệt.", Location = new Point(24, 72), Size = new Size(572, 70) };
            var destinationLabel = new Label { Text = "Thư mục cài ứng dụng", AutoSize = true, Location = new Point(24, 127), Visible = !uninstall };
            var destination = new TextBox { Text = Root, Location = new Point(24, 154), Size = new Size(452, 28), AccessibleName = "Thư mục cài ứng dụng", Visible = !uninstall, TabIndex = 0 };
            var browse = new Button { Text = "Duyệt…", Location = new Point(486, 151), Size = new Size(110, 34), Visible = !uninstall, TabIndex = 1 };
            browse.Click += (sender, e) =>
            {
                using (var picker = new FolderBrowserDialog { Description = "Chọn thư mục riêng chứa app và thư mục ext, ví dụ D:\\Apps\\IQIYI-VI.", SelectedPath = destination.Text, ShowNewFolderButton = true })
                    if (picker.ShowDialog(form) == DialogResult.OK) destination.Text = picker.SelectedPath;
            };
            var startup = new CheckBox { Text = "Chạy dịch vụ nền khi đăng nhập Windows", Checked = true, AutoSize = true, Location = new Point(24, 204), Visible = !uninstall, TabIndex = 2 };
            var desktop = new CheckBox { Text = "Tạo biểu tượng ngoài màn hình Desktop", Checked = true, AutoSize = true, Location = new Point(24, 234), Visible = !uninstall, TabIndex = 3 };
            var extensionHelp = new Label { Text = "Tiện ích được cài trong thư mục ext cạnh app.\nChrome/Edge → Tiện ích → Chế độ dành cho nhà phát triển →\nTải tiện ích đã giải nén → chọn thư mục ext.", Location = new Point(24, 278), Size = new Size(572, 76), Visible = !uninstall };
            var status = new Label { AutoSize = false, Location = new Point(24, 201), Size = new Size(572, 72), Visible = false };
            var progress = new ProgressBar { Location = new Point(24, 365), Size = new Size(572, 12), Style = ProgressBarStyle.Marquee, Visible = false };
            var openExtension = new Button { Text = "Mở thư mục tiện ích", Location = new Point(24, 402), Size = new Size(195, 38), Visible = false, TabIndex = 4 };
            openExtension.Click += (sender, e) =>
            {
                try { Process.Start(new ProcessStartInfo(Path.Combine(Root, "ext")) { UseShellExecute = true }); }
                catch (Exception error) { MessageBox.Show(form, error.Message, "Thư mục tiện ích", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            };
            var action = new Button { Text = uninstall ? "Gỡ cài đặt" : "Cài đặt", Location = new Point(466, 402), Size = new Size(130, 38), TabIndex = 5 };
            var cancel = new Button { Text = "Đóng", Location = new Point(341, 402), Size = new Size(115, 38), DialogResult = DialogResult.Cancel, TabIndex = 6 };
            form.Controls.AddRange(new Control[] { title, detail, destinationLabel, destination, browse, startup, desktop, extensionHelp, status, progress, openExtension, action, cancel });
            form.CancelButton = cancel;
            form.AcceptButton = action;
            bool working = false, finished = false;
            form.FormClosing += (sender, e) => { if (working) e.Cancel = true; };
            action.Click += async (sender, e) =>
            {
                if (finished)
                {
                    try
                    {
                        Process.Start(new ProcessStartInfo(Path.Combine(Root, "IQIYI-VI.exe")) { WorkingDirectory = Root, UseShellExecute = false });
                        form.Close();
                    }
                    catch (Exception error) { status.Text = error.Message; }
                    return;
                }
                try
                {
                    if (!uninstall)
                    {
                        string selected = NormalizeRoot(destination.Text);
                        string installed = InstalledRoot();
                        if (installed != null && File.Exists(Path.Combine(installed, "IQIYI-VI.exe")) && !String.Equals(selected, NormalizeRoot(installed), StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("App đã cài tại " + installed + ".\nNâng cấp tại thư mục này để giữ dữ liệu. Gỡ bản cũ trước nếu muốn đổi thư mục.");
                        Root = selected;
                        destination.Text = Root;
                    }
                }
                catch (Exception error) { MessageBox.Show(form, error.Message, "Thư mục cài ứng dụng", MessageBoxButtons.OK, MessageBoxIcon.Warning); destination.Focus(); return; }
                working = true;
                action.Enabled = cancel.Enabled = destination.Enabled = browse.Enabled = false;
                bool autoStart = startup.Checked, shortcut = desktop.Checked;
                startup.Visible = desktop.Visible = false;
                status.Text = uninstall ? "Đang gỡ app…" : "Đang giải nén và kiểm tra app…";
                status.Visible = true;
                progress.Visible = true;
                try
                {
                    await Task.Run(() => { if (uninstall) Uninstall(); else Install(autoStart, shortcut); });
                    status.Text = uninstall ? "Đã gỡ app. Dữ liệu cá nhân được giữ trong:\n" + Root : "Đã cài đặt. Bạn có thể mở app hoặc nạp tiện ích trình duyệt.\nKhi cập nhật, bấm Tải lại tiện ích rồi tải lại trang iQIYI.";
                    finished = true;
                    openExtension.Visible = !uninstall;
                    action.Text = "Mở app";
                    action.Enabled = true;
                    action.Visible = !uninstall;
                    cancel.Text = "Hoàn tất";
                }
                catch (Exception error)
                {
                    status.Text = error.Message;
                    action.Enabled = true;
                    destination.Enabled = browse.Enabled = true;
                    startup.Visible = desktop.Visible = false;
                }
                finally { working = false; cancel.Enabled = true; progress.Visible = false; }
            };
            Application.Run(form);
        }
    }

    internal static string SafePath(string root, string relative)
    {
        if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.Contains(':'))
            throw new InvalidDataException("Đường dẫn trong gói không hợp lệ.");
        string parent = Path.GetFullPath(root).TrimEnd('\\') + "\\";
        string path = Path.GetFullPath(Path.Combine(parent, relative.Replace('/', '\\')));
        if (!path.StartsWith(parent, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Đường dẫn vượt thư mục app.");
        for (string current = path; current != null && current.Length >= parent.Length - 1; current = Path.GetDirectoryName(current))
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Đường dẫn trong app không được là liên kết.");
        return path;
    }

    private static string NewStage()
    {
        string stage = Path.Combine(Path.GetTempPath(), "IQIYI-VI-Stage-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        return stage;
    }

    private static void DeleteStage(string stage)
    {
        string parent = Path.GetFullPath(Path.GetTempPath()).TrimEnd('\\') + "\\IQIYI-VI-Stage-";
        if (!Path.GetFullPath(stage).StartsWith(parent, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Thư mục tạm không hợp lệ.");
        if (Directory.Exists(stage)) Directory.Delete(stage, true);
    }

    private static void ExtractPackage(string stage)
    {
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.zip"))
        using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
        {
            string prefix = null;
            foreach (var entry in archive.Entries)
            {
                int slash = entry.FullName.IndexOf('/');
                if (slash <= 0) throw new InvalidDataException("Gói app không có thư mục gốc.");
                if (prefix == null) prefix = entry.FullName.Substring(0, slash + 1);
                if (!entry.FullName.StartsWith(prefix, StringComparison.Ordinal)) throw new InvalidDataException("Gói app có nhiều thư mục gốc.");
                string relative = entry.FullName.Substring(slash + 1);
                if (relative.Length == 0 || relative.EndsWith("/")) continue;
                string target = SafePath(stage, relative);
                if (!paths.Add(relative)) throw new InvalidDataException("Gói app trùng đường dẫn.");
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                entry.ExtractToFile(target);
            }
        }
        if (!File.Exists(Path.Combine(stage, "IQIYI-VI.exe")) || !File.Exists(Path.Combine(stage, "Uninstall.exe")))
            throw new InvalidDataException("Gói app thiếu file khởi động.");
        File.WriteAllText(Path.Combine(stage, Manifest), Json.Serialize(paths.OrderBy(p => p).ToArray()));
    }

    private static string[] ReadManifest(string root)
    {
        string path = Path.Combine(root, Manifest);
        return File.Exists(path) ? Json.Deserialize<string[]>(File.ReadAllText(path)) : new string[0];
    }

    private static void RunPython(string root, string action)
    {
        var info = new ProcessStartInfo(Path.Combine(root, "runtime", "python.exe"), Quote(Path.Combine(root, "desktop.py")) + " " + action)
        { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        using (var process = Process.Start(info))
        {
            // Read both pipes concurrently; Python's own log retains details for normal actions.
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            Task.WaitAll(stdout, stderr);
            if (process.ExitCode != 0) throw new InvalidOperationException("Chưa hoàn tất. Nếu app đang dịch hoặc tải phụ đề, hãy chờ xong rồi thử lại.\n" + stdout.Result + stderr.Result);
        }
    }

    internal static void CopyPackage(string stage, string root)
    {
        string[] files = ReadManifest(stage);
        var previous = ReadManifest(root);
        // Validate the complete manifests before any deletion or overwrite.
        foreach (string path in files.Concat(previous)) SafePath(root, path);
        var managed = new HashSet<string>(previous, StringComparer.OrdinalIgnoreCase);
        foreach (string path in files)
            if (File.Exists(SafePath(root, path)) && !managed.Contains(path))
                throw new IOException("Thư mục đã chứa file ngoài bộ cài: " + path + ". Chọn thư mục riêng cho app.");
        string rollback = NewStage();
        bool keepRollback = false;
        var originals = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var touched = files.Concat(previous).Concat(new[] { Manifest }).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        try
        {
            foreach (string relative in touched)
            {
                string source = SafePath(root, relative);
                if (!File.Exists(source)) continue;
                string backup = SafePath(rollback, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(backup));
                File.Copy(source, backup);
                originals.Add(relative);
            }
            try
            {
                foreach (string relative in files)
                {
                    string target = SafePath(root, relative);
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    File.Copy(SafePath(stage, relative), target, true);
                }
                foreach (string relative in previous.Except(files, StringComparer.OrdinalIgnoreCase))
                    File.Delete(SafePath(root, relative));
                File.Copy(Path.Combine(stage, Manifest), Path.Combine(root, Manifest), true);
            }
            catch (Exception copyError)
            {
                try
                {
                    foreach (string relative in touched)
                    {
                        string target = SafePath(root, relative);
                        if (originals.Contains(relative)) File.Copy(SafePath(rollback, relative), target, true);
                        else if (File.Exists(target)) File.Delete(target);
                    }
                }
                catch (Exception restoreError)
                {
                    keepRollback = true;
                    throw new IOException("Cập nhật lỗi và chưa khôi phục đủ file. Bản sao an toàn nằm tại " + rollback + ".\n" + copyError.Message + "\n" + restoreError.Message, restoreError);
                }
                throw;
            }
        }
        finally { if (!keepRollback) DeleteStage(rollback); }
    }

    private static void Install(bool startup, bool desktop)
    {
        Root = NormalizeRoot(Root);
        Directory.CreateDirectory(Root);
        string probe = Path.Combine(Root, ".write-check-" + Guid.NewGuid().ToString("N"));
        try { File.WriteAllText(probe, ""); }
        catch (UnauthorizedAccessException) { throw new IOException("Không có quyền ghi vào thư mục này. Chọn thư mục thuộc tài khoản của bạn."); }
        finally { if (File.Exists(probe)) File.Delete(probe); }
        string stage = NewStage();
        try
        {
            ExtractPackage(stage);
            RunPython(stage, "--check");
            if (File.Exists(Path.Combine(Root, "desktop.py"))) RunPython(Root, "stop");
            CopyPackage(stage, Root);
            MakeShortcut(Environment.GetFolderPath(Environment.SpecialFolder.Programs));
            if (desktop) MakeShortcut(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory));
            else File.Delete(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "iQIYI – Quản lý phụ đề.lnk"));
            using (var key = Registry.CurrentUser.CreateSubKey(RunPath))
            {
                if (startup) key.SetValue("IQIYI-VI-Manager", Quote(Path.Combine(Root, "IQIYI-VI.exe")) + " background");
                else key.DeleteValue("IQIYI-VI-Manager", false);
            }
            using (var key = Registry.CurrentUser.CreateSubKey(RegistryPath))
            {
                key.SetValue("DisplayName", "iQIYI – Quản lý phụ đề");
                key.SetValue("DisplayVersion", Version);
                key.SetValue("Publisher", "IQIYI-VI");
                key.SetValue("InstallLocation", Root);
                key.SetValue("DisplayIcon", Path.Combine(Root, "IQIYI-VI.exe"));
                key.SetValue("UninstallString", Quote(Path.Combine(Root, "Uninstall.exe")));
                key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
        }
        finally { DeleteStage(stage); }
    }

    private static string Quote(string value) { return "\"" + value + "\""; }

    private static void MakeShortcut(string folder)
    {
        Directory.CreateDirectory(folder);
        Type type = Type.GetTypeFromProgID("WScript.Shell");
        object shell = Activator.CreateInstance(type);
        object shortcut = type.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { Path.Combine(folder, "iQIYI – Quản lý phụ đề.lnk") });
        Type shortcutType = shortcut.GetType();
        shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { Path.Combine(Root, "IQIYI-VI.exe") });
        shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { Root });
        shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shortcut);
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
    }

    private static void Uninstall()
    {
        if (!File.Exists(Path.Combine(Root, Manifest))) throw new InvalidDataException("Không có danh sách file đã cài; giữ nguyên thư mục app.");
        RunPython(Root, "uninstall");
        foreach (string folder in new[] { Environment.GetFolderPath(Environment.SpecialFolder.Programs), Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory) })
            File.Delete(Path.Combine(folder, "iQIYI – Quản lý phụ đề.lnk"));
        using (var key = Registry.CurrentUser.OpenSubKey(RunPath, true))
        {
            if (key != null && (key.GetValue("IQIYI-VI-Manager", "") as string) == Quote(Path.Combine(Root, "IQIYI-VI.exe")) + " background")
                key.DeleteValue("IQIYI-VI-Manager", false);
        }
        string[] files = ReadManifest(Root);
        RemovePackage(Root, files);
        Registry.CurrentUser.DeleteSubKeyTree(RegistryPath, false);
    }

    internal static void RemovePackage(string root, string[] files)
    {
        foreach (string path in files) SafePath(root, path);
        foreach (string path in files) File.Delete(SafePath(root, path));
        File.Delete(Path.Combine(root, Manifest));
        // Only prune parents of managed files, never traverse user data or unrelated folders.
        var folders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string path in files)
            for (string folder = Path.GetDirectoryName(SafePath(root, path)); folder.Length > root.TrimEnd('\\').Length; folder = Path.GetDirectoryName(folder))
                folders.Add(folder);
        foreach (string folder in folders.OrderByDescending(p => p.Length))
            if (Directory.Exists(folder) && !Directory.EnumerateFileSystemEntries(folder).Any()) Directory.Delete(folder);
        if (!Directory.EnumerateFileSystemEntries(root).Any()) Directory.Delete(root);
    }
}
