using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class DesktopLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            var root = AppDomain.CurrentDomain.BaseDirectory;
            var allowed = new[] { "open", "iqiyi", "restore", "stop", "background", "--check" };
            if (args.Length > 1 || (args.Length == 1 && Array.IndexOf(allowed, args[0]) < 0))
                throw new ArgumentException("Thao tác hợp lệ: open, iqiyi, restore, stop, background, --check.");
            var python = Path.Combine(root, "runtime", "pythonw.exe");
            var script = Path.Combine(root, "desktop.py");
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("Hãy giải nén toàn bộ gói app trước khi mở IQIYI-VI.exe.");
            var info = new ProcessStartInfo(python)
            {
                Arguments = "\"" + script + "\"" + (args.Length == 0 ? "" : " " + args[0]),
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using (var process = Process.Start(info))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "iQIYI Việt hóa", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
