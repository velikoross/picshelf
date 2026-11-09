import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk
from photos import duplicates, move_photo, scan


class PicShelf:
    def __init__(self, window):
        self.window = window
        self.folder = None
        self.paths = {}
        self.busy = False
        self.worker = ThreadPoolExecutor(max_workers=1)
        window.title("PicShelf")
        window.geometry("960x600")
        toolbar = ttk.Frame(window, padding=8)
        toolbar.pack(fill="x")
        self.buttons = []
        for title, action in [
            ("Открыть папку…", self.open_folder),
            ("Все фото", self.load),
            ("Найти дубликаты", lambda: self.load(True)),
            ("Переместить выбранные…", self.move),
        ]:
            button = ttk.Button(toolbar, text=title, command=action)
            button.pack(side="left", padx=2)
            self.buttons.append(button)
        panes = ttk.Panedwindow(window, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10)
        left = ttk.Frame(panes)
        panes.add(left, weight=3)
        self.tree = ttk.Treeview(left, show="tree", selectmode="extended")
        scrollbar = ttk.Scrollbar(left, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(fill="both", expand=True)
        self.preview = ttk.Label(panes, anchor="center", width=32)
        panes.add(self.preview, weight=2)
        self.tree.bind("<<TreeviewSelect>>", self.show_preview)
        self.status = tk.StringVar(value="Откройте папку с фотографиями")
        ttk.Label(window, textvariable=self.status, padding=8).pack(anchor="w")
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.controls()

    def controls(self):
        for index, button in enumerate(self.buttons):
            enabled = not self.busy and (index == 0 or self.folder is not None)
            if index == 3:
                enabled = enabled and bool(self.selection())
            button.configure(state="normal" if enabled else "disabled")

    def selection(self):
        return [self.paths[item] for item in self.tree.selection() if item in self.paths]

    def close(self):
        if self.busy:
            messagebox.showinfo("PicShelf", "Дождитесь завершения операции.")
            return
        self.worker.shutdown(wait=False)
        self.window.destroy()

    def run(self, label, task, done):
        self.busy = True
        self.controls()
        self.status.set(label)
        future = self.worker.submit(task)

        def poll():
            if not future.done():
                self.window.after(80, poll)
                return
            self.busy = False
            try:
                done(future.result())
            except Exception as exc:
                self.status.set("Ошибка операции")
                messagebox.showerror("PicShelf", str(exc))
            self.controls()

        self.window.after(80, poll)

    def open_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.folder = Path(path)
            self.window.title(f"PicShelf — {path}")
            self.load()

    def load(self, only_duplicates=False):
        def read():
            errors = []
            photos = scan(self.folder, errors.append)
            groups = duplicates(photos, errors.append) if only_duplicates else []
            return photos, groups, errors

        def display(result):
            photos, groups, errors = result
            self.tree.delete(*self.tree.get_children())
            self.paths.clear()
            self.preview.configure(image="", text="")
            if only_duplicates:
                for number, group in enumerate(groups, 1):
                    parent = self.tree.insert("", "end", text=f"Группа {number} · {len(group)} копии", open=True)
                    for path in group:
                        self.insert(parent, path)
                summary = f"Групп дубликатов: {len(groups)} · Файлов в группах: {len(self.paths)}"
            else:
                for path, _ in photos:
                    self.insert("", path)
                summary = f"Фотографий: {len(photos)}"
            self.status.set(summary + "    |    Выделение нескольких файлов: Ctrl или Shift")
            self.errors(errors)

        self.run("Идёт поиск дубликатов…" if only_duplicates else "Чтение папки…", read, display)

    def insert(self, parent, path):
        item = self.tree.insert(parent, "end", text=str(path.relative_to(self.folder)))
        self.paths[item] = path

    def show_preview(self, event):
        self.controls()
        path = self.paths.get(self.tree.focus())
        if not path or not self.selection():
            self.preview.configure(image="", text="")
            return
        try:
            with Image.open(path) as photo:
                photo.thumbnail((max(200, self.preview.winfo_width() - 12),
                                 max(200, self.preview.winfo_height() - 12)))
                self.preview.image = ImageTk.PhotoImage(ImageOps.exif_transpose(photo))
            self.preview.configure(image=self.preview.image, text="")
        except (OSError, ValueError, Image.DecompressionBombError):
            self.preview.configure(image="", text="Предпросмотр недоступен")

    @staticmethod
    def errors(errors):
        if errors:
            messagebox.showwarning("PicShelf", f"Ошибок: {len(errors)}\n" + "\n".join(map(str, errors[:8])))

    def move(self):
        paths = self.selection()
        destination = filedialog.askdirectory(title="Папка назначения")
        if not destination:
            return

        def transfer():
            errors = []
            moved = skipped = 0
            for path in paths:
                try:
                    if move_photo(path, Path(destination)) is None:
                        skipped += 1
                    else:
                        moved += 1
                except OSError as exc:
                    errors.append(f"{path}: {exc}")
            return moved, skipped, errors

        def finished(result):
            moved, skipped, errors = result
            messagebox.showinfo("Перемещение", f"Перемещено: {moved}\nУже в папке: {skipped}\nОшибок: {len(errors)}")
            self.errors(errors)
            self.load()

        self.run("Перемещение фотографий…", transfer, finished)


if __name__ == "__main__":
    root = tk.Tk()
    PicShelf(root)
    root.mainloop()
