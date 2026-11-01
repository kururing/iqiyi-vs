using System;
using System.IO;
using System.Web.Script.Serialization;

internal static class InstallerFiles
{
    private static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
    public static int Main(string[] args)
    {
        string temporary = args[0]; // The Python test owns this TemporaryDirectory.
        string stage = Path.Combine(temporary, "gói cài mới");
        string root = Path.Combine(temporary, "app đang dùng");
        Assert(AppInstaller.NormalizeRoot(root + "\\") == root, "Custom install root did not normalize");
        foreach (string invalid in new[] { "", "relative/app", "C:relative", "C:\\", "C:\\app?", "\\\\server\\share" })
        {
            bool rejected = false;
            try { AppInstaller.NormalizeRoot(invalid); } catch (Exception) { rejected = true; }
            Assert(rejected, "Unsafe install root accepted: " + invalid);
        }
        Directory.CreateDirectory(stage);
        Directory.CreateDirectory(Path.Combine(root, ".local"));
        Directory.CreateDirectory(Path.Combine(root, "subtitles", "library"));
        File.WriteAllText(Path.Combine(stage, "app.py"), "new app");
        Directory.CreateDirectory(Path.Combine(stage, "ext"));
        File.WriteAllText(Path.Combine(stage, "ext", "manifest.json"), "{\"manifest_version\":3}");
        string manifest = "[\"app.py\",\"ext/manifest.json\"]";
        File.WriteAllText(Path.Combine(stage, ".installed-files.json"), manifest);
        string fresh = Path.Combine(temporary, "fresh app");
        AppInstaller.CopyPackage(stage, fresh);
        Assert(File.ReadAllText(Path.Combine(fresh, "app.py")) == "new app", "Fresh install failed");
        Assert(File.Exists(Path.Combine(fresh, "ext", "manifest.json")), "Browser extension missing");
        Assert(AppInstaller.UninstallRoot(fresh + "\\", fresh) == fresh, "Custom uninstall root was not accepted");
        bool wrongRoot = false;
        try { AppInstaller.UninstallRoot(fresh, root); } catch (InvalidDataException) { wrongRoot = true; }
        Assert(wrongRoot, "Uninstaller accepted a different registered root");
        AppInstaller.RemovePackage(fresh, new[] { "app.py", "ext/manifest.json" });
        Assert(!Directory.Exists(fresh), "Clean uninstall retained empty install directory");
        File.WriteAllText(Path.Combine(root, "app.py"), "old app");
        File.WriteAllText(Path.Combine(root, "obsolete.py"), "obsolete");
        File.WriteAllText(Path.Combine(root, ".local", "checkpoint.json"), "saved progress");
        File.WriteAllText(Path.Combine(root, "subtitles", "library", "source.srt"), "subtitle");
        File.WriteAllText(Path.Combine(root, ".installed-files.json"), "[\"app.py\",\"obsolete.py\"]");
        AppInstaller.CopyPackage(stage, root);
        Assert(File.ReadAllText(Path.Combine(root, "app.py")) == "new app", "Upgrade did not replace code");
        Assert(!File.Exists(Path.Combine(root, "obsolete.py")), "Stale package code retained");
        AppInstaller.CopyPackage(stage, root); // Repair is idempotent.
        // Fail after replacing the first file; the old code and manifest must be restored.
        File.WriteAllText(Path.Combine(stage, "app.py"), "broken upgrade");
        File.WriteAllText(Path.Combine(stage, ".installed-files.json"), "[\"app.py\",\"missing.py\"]");
        bool copyFailed = false;
        try { AppInstaller.CopyPackage(stage, root); } catch (FileNotFoundException) { copyFailed = true; }
        Assert(copyFailed, "Incomplete update unexpectedly succeeded");
        Assert(File.ReadAllText(Path.Combine(root, "app.py")) == "new app", "Failed update did not restore code");
        Assert(File.ReadAllText(Path.Combine(root, ".installed-files.json")) == manifest, "Failed update did not restore manifest");
        File.WriteAllText(Path.Combine(stage, "app.py"), "new app");
        File.WriteAllText(Path.Combine(stage, ".installed-files.json"), manifest);
        string occupied = Path.Combine(temporary, "unmanaged app");
        Directory.CreateDirectory(occupied);
        File.WriteAllText(Path.Combine(occupied, "app.py"), "personal file");
        bool conflict = false;
        try { AppInstaller.CopyPackage(stage, occupied); } catch (IOException) { conflict = true; }
        Assert(conflict && File.ReadAllText(Path.Combine(occupied, "app.py")) == "personal file", "Unmanaged file overwritten");
        foreach (string path in new[] { "../outside.txt", "..\\outside.txt", "C:\\outside.txt", "\\\\server\\share", "runtime/file:stream" })
        {
            bool rejected = false;
            try { AppInstaller.SafePath(root, path); } catch (InvalidDataException) { rejected = true; }
            Assert(rejected, "Unsafe path accepted: " + path);
        }
        File.WriteAllText(Path.Combine(stage, ".installed-files.json"), "[\"app.py\",\"../outside.txt\"]");
        bool invalidManifest = false;
        try { AppInstaller.CopyPackage(stage, root); } catch (InvalidDataException) { invalidManifest = true; }
        Assert(invalidManifest, "Unsafe manifest accepted");
        string[] files = new JavaScriptSerializer().Deserialize<string[]>(File.ReadAllText(Path.Combine(root, ".installed-files.json")));
        Directory.CreateDirectory(Path.Combine(root, "unrelated empty folder"));
        AppInstaller.RemovePackage(root, files);
        Assert(!File.Exists(Path.Combine(root, "app.py")), "Uninstall retained package code");
        Assert(File.ReadAllText(Path.Combine(root, ".local", "checkpoint.json")) == "saved progress", "Lost translation progress");
        Assert(File.ReadAllText(Path.Combine(root, "subtitles", "library", "source.srt")) == "subtitle", "Lost library");
        Assert(Directory.Exists(Path.Combine(root, "unrelated empty folder")), "Uninstall touched unrelated folders");
        Console.WriteLine("PASS: custom install/uninstall roots, extension files, clean install/upgrade/repair/remove, failed update rollback, Unicode paths, library and checkpoints preserved, unsafe paths and unmanaged overwrites rejected.");
        return 0;
    }
}
