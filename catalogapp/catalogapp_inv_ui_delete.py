import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import scrolledtext

import requests

try:
    from catalogapp.catalogapp_inv_ui import ArtCatalogApp, BASE_URL, api_headers
except ImportError:
    from catalogapp_inv_ui import ArtCatalogApp, BASE_URL, api_headers


class ArtCatalogAppWithDelete(ArtCatalogApp):
    def _delete_listing_by_title(self, title):
        response = requests.post(
            f"{BASE_URL}/artworks/delete_artwork/",
            json={"title": title},
            headers=api_headers(),
            timeout=30,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error") or response.text
            except ValueError:
                detail = response.text
            raise RuntimeError(detail or f"Delete failed with status {response.status_code}")
        return response

    def _save_artwork_order(self, order_ids):
        response = requests.post(
            f"{BASE_URL}/artworks/reorder_artworks/",
            json={"order": [int(artwork_id) for artwork_id in order_ids]},
            headers=api_headers({"Content-Type": "application/json"}),
            timeout=30,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error") or response.text
            except ValueError:
                detail = response.text
            raise RuntimeError(detail or f"Order save failed with status {response.status_code}")
        try:
            return response.json().get("artworks", [])
        except ValueError as exc:
            raise RuntimeError("Order save returned an invalid response.") from exc

    def delete_artwork(self):
        try:
            artworks = self._fetch_website_artworks()
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to fetch artworks: {exc}")
            return
        if not artworks:
            messagebox.showinfo("No Listings", "No website listings found.")
            return

        win = tk.Toplevel(self.master)
        win.title("Delete Website Listing")
        win.geometry("760x620")
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Delete Website Listing", style="Header.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Select one or more listings to permanently remove from SecondState.Art.", style="Subtle.TLabel").pack(anchor="w", pady=(4, 10))

        tree = ttk.Treeview(frame, columns=("Artist", "Title", "Price"), show="headings", selectmode="extended")
        for col in ("Artist", "Title", "Price"):
            tree.heading(col, text=col)
            tree.column(col, width=180, stretch=True)
        tree.pack(fill=tk.BOTH, expand=True)
        for art in artworks:
            tree.insert("", tk.END, iid=str(art.get("id")), values=(art.get("artist", ""), art.get("title", ""), art.get("price", "")))

        def delete_selected():
            selected_ids = tree.selection()
            if not selected_ids:
                messagebox.showwarning("No Selection", "Select at least one listing to delete.", parent=win)
                return
            selected = [art for art in artworks if str(art.get("id")) in selected_ids]
            label = "\n".join(f"{art.get('artist', '')} — {art.get('title', '')}" for art in selected)
            if not messagebox.askyesno(
                "Confirm Delete Listing",
                f"Permanently delete {len(selected)} listing(s) from SecondState.Art?\n\n{label}",
                icon="warning",
                parent=win,
            ):
                return
            errors = []
            for art in selected:
                try:
                    self._delete_listing_by_title(art.get("title", ""))
                    tree.delete(str(art.get("id")))
                    artworks.remove(art)
                except Exception as exc:
                    errors.append(f"{art.get('title', '')}: {exc}")
            if errors:
                messagebox.showwarning("Delete Finished with Issues", "\n".join(errors[:8]), parent=win)
            else:
                messagebox.showinfo("Deleted", "Selected listing(s) removed from SecondState.Art.", parent=win)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Delete Selected Listing", command=delete_selected, style="Danger.TButton").pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side=tk.RIGHT)

    def edit_website_listings(self):
        try:
            artworks = self._fetch_website_artworks()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch artworks: {e}")
            return
        if not artworks:
            messagebox.showinfo("No Listings", "No website listings found.")
            return
        win = tk.Toplevel(self.master)
        win.title("Edit Website Listings")
        win.geometry("1180x760")
        paned = ttk.Panedwindow(win, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        left = ttk.Frame(paned, padding=8)
        right = ttk.Frame(paned, padding=8)
        paned.add(left, weight=1)
        paned.add(right, weight=2)
        ttk.Label(left, text="Website Listings", style="Header.TLabel").pack(anchor="w")
        ttk.Label(left, text="Drag rows or use Move Up / Move Down, then Save Order.", style="Subtle.TLabel").pack(anchor="w", pady=(4, 0))
        listing_tree = ttk.Treeview(left, columns=("Artist", "Title", "Price"), show="headings")
        for col in ("Artist", "Title", "Price"):
            listing_tree.heading(col, text=col)
            listing_tree.column(col, width=140, stretch=True)
        listing_tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        for art in artworks:
            listing_tree.insert("", tk.END, iid=str(art.get("id")), values=(art.get("artist", ""), art.get("title", ""), art.get("price", "")))

        fields, selected = {}, {"art": None}
        is_available = tk.BooleanVar(value=True)
        form = ttk.Frame(right)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        row_num = 0
        ttk.Label(form, text="Edit Listing", style="Header.TLabel").grid(row=row_num, column=0, columnspan=2, sticky="w")
        row_num += 1
        for key, label in self.EDIT_FIELDS:
            ttk.Label(form, text=label).grid(row=row_num, column=0, sticky="w", padx=(0, 8), pady=3)
            entry = ttk.Entry(form)
            entry.grid(row=row_num, column=1, sticky="ew", pady=3)
            fields[key] = entry
            row_num += 1
        ttk.Label(form, text="Notes / signature text").grid(row=row_num, column=0, sticky="nw", padx=(0, 8), pady=3)
        notes_text = scrolledtext.ScrolledText(form, wrap=tk.WORD, height=4, font=("Segoe UI", 10))
        notes_text.grid(row=row_num, column=1, sticky="ew", pady=3)
        row_num += 1
        ttk.Label(form, text="Description").grid(row=row_num, column=0, sticky="nw", padx=(0, 8), pady=3)
        desc_text = scrolledtext.ScrolledText(form, wrap=tk.WORD, height=8, font=("Segoe UI", 10))
        desc_text.grid(row=row_num, column=1, sticky="nsew", pady=3)
        form.rowconfigure(row_num, weight=1)
        row_num += 1
        ttk.Checkbutton(form, text="Available", variable=is_available).grid(row=row_num, column=1, sticky="w")
        row_num += 1
        image_box = ttk.LabelFrame(form, text="Images")
        image_box.grid(row=row_num, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        image_list = ttk.Frame(image_box, padding=6)
        image_list.pack(fill=tk.X)
        image_status = ttk.Label(image_box, text="", style="Subtle.TLabel")
        image_status.pack(anchor="w", padx=6, pady=(0, 6))
        delete_image_vars, add_image_paths = {}, []
        status = ttk.Label(right, text="Select a listing to edit.", style="Subtle.TLabel")
        status.pack(anchor="w", pady=(8, 0))

        def clear_form():
            selected["art"] = None
            for widget in fields.values():
                widget.delete(0, tk.END)
            notes_text.delete("1.0", tk.END)
            desc_text.delete("1.0", tk.END)
            for child in image_list.winfo_children():
                child.destroy()
            status.config(text="Select a listing to edit.")

        def payload():
            data = {key: widget.get().strip() for key, widget in fields.items()}
            data["description"] = notes_text.get("1.0", tk.END).strip()
            data["catalog_description"] = desc_text.get("1.0", tk.END).strip()
            data["is_available"] = is_available.get()
            return data

        def populate(art):
            selected["art"] = art
            for key, widget in fields.items():
                widget.delete(0, tk.END)
                widget.insert(0, art.get(key, "") or "")
            notes_text.delete("1.0", tk.END)
            notes_text.insert(tk.END, art.get("description", "") or "")
            desc_text.delete("1.0", tk.END)
            desc_text.insert(tk.END, art.get("catalog_description", "") or "")
            is_available.set(bool(art.get("is_available", True)))
            add_image_paths.clear()
            for child in image_list.winfo_children():
                child.destroy()
            delete_image_vars.clear()
            for image in art.get("images", []) or []:
                var = tk.BooleanVar(value=False)
                delete_image_vars[str(image.get("id"))] = var
                ttk.Checkbutton(image_list, text=f"Delete image {image.get('id')}: {image.get('url', '')}", variable=var).pack(anchor="w", fill=tk.X)
            image_status.config(text="")
            status.config(text=f"Editing listing ID {art.get('id')}")

        def replace_artwork(updated):
            updated_id = str(updated.get("id"))
            for index, existing in enumerate(artworks):
                if str(existing.get("id")) == updated_id:
                    artworks[index] = updated
                    return
            artworks.append(updated)

        def refresh_listing_tree(new_artworks, focus_id=None):
            artworks[:] = new_artworks
            for item_id in listing_tree.get_children(""):
                listing_tree.delete(item_id)
            for art in artworks:
                listing_tree.insert("", tk.END, iid=str(art.get("id")), values=(art.get("artist", ""), art.get("title", ""), art.get("price", "")))

            target_id = str(focus_id) if focus_id else None
            if not target_id and artworks:
                target_id = str(artworks[0].get("id"))
            if target_id and listing_tree.exists(target_id):
                listing_tree.selection_set(target_id)
                listing_tree.focus(target_id)
                art = next((a for a in artworks if str(a.get("id")) == target_id), None)
                if art:
                    populate(art)
            else:
                clear_form()

        def current_order_ids():
            return [int(item_id) for item_id in listing_tree.get_children("")]

        def sync_artworks_from_tree():
            artwork_by_id = {str(art.get("id")): art for art in artworks}
            artworks[:] = [artwork_by_id[item_id] for item_id in listing_tree.get_children("") if item_id in artwork_by_id]

        def on_select(_event=None):
            sel = listing_tree.selection()
            if sel:
                art = next((a for a in artworks if str(a.get("id")) == sel[0]), None)
                if art:
                    populate(art)

        def add_images():
            paths = filedialog.askopenfilenames(title="Add images", filetypes=[("Image Files", "*.jpg *.jpeg *.png")], parent=win)
            add_image_paths.extend(paths)
            image_status.config(text=f"{len(add_image_paths)} new image(s) queued.")

        def generate():
            art = selected["art"]
            if not art:
                return
            try:
                data = payload()
                data["use_web"] = True
                response = requests.post(f"{BASE_URL}/artworks/{art.get('id')}/generate_description/", json=data, headers=api_headers({"Content-Type": "application/json"}), timeout=70)
                response.raise_for_status()
                desc_text.delete("1.0", tk.END)
                desc_text.insert(tk.END, response.json().get("description", ""))
                status.config(text="Draft inserted. Review/edit, then Save Changes.")
            except Exception as exc:
                messagebox.showerror("Generate Failed", str(exc), parent=win)

        def save():
            art = selected["art"]
            if not art:
                return
            data = payload()
            for image_id, var in delete_image_vars.items():
                if var.get():
                    data.setdefault("delete_image_ids", []).append(image_id)
            data_items = []
            for key, value in data.items():
                if isinstance(value, list):
                    data_items.extend((key, item) for item in value)
                else:
                    data_items.append((key, str(value)))
            files = []
            try:
                for i, path in enumerate(add_image_paths):
                    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                    files.append((f"image_{i}", (os.path.basename(path), open(path, "rb"), mime)))
                response = requests.post(f"{BASE_URL}/artworks/{art.get('id')}/update_artwork/", data=data_items, files=files, headers=api_headers(), timeout=70)
                response.raise_for_status()
                updated = response.json().get("artwork", {})
                updated.setdefault("id", art.get("id"))
                replace_artwork(updated)
                listing_tree.item(str(updated.get("id")), values=(updated.get("artist", ""), updated.get("title", ""), updated.get("price", "")))
                populate(updated)
                status.config(text="Saved changes to website listing.")
            except Exception as exc:
                messagebox.showerror("Save Failed", str(exc), parent=win)
            finally:
                for _name, file_tuple in files:
                    try:
                        file_tuple[1].close()
                    except Exception:
                        pass

        def delete_listing():
            art = selected["art"]
            if not art:
                messagebox.showwarning("No Selection", "Select a listing to delete.", parent=win)
                return
            label = f"{art.get('artist', '')} — {art.get('title', '')}"
            if not messagebox.askyesno(
                "Delete Listing",
                f"Permanently delete this listing from SecondState.Art?\n\n{label}",
                icon="warning",
                parent=win,
            ):
                return
            try:
                self._delete_listing_by_title(art.get("title", ""))
                art_id = str(art.get("id"))
                listing_tree.delete(art_id)
                artworks.remove(art)
                sync_artworks_from_tree()
                clear_form()
                if artworks:
                    next_id = str(artworks[0].get("id"))
                    listing_tree.selection_set(next_id)
                    listing_tree.focus(next_id)
                    populate(artworks[0])
                status.config(text=f"Deleted listing: {label}")
            except Exception as exc:
                messagebox.showerror("Delete Failed", str(exc), parent=win)

        def mark_order_changed():
            status.config(text="Order changed. Click Save Order to publish it.")

        def move_item(item_id, index):
            children = list(listing_tree.get_children(""))
            if not item_id or item_id not in children:
                return
            target_index = max(0, min(index, len(children) - 1))
            if listing_tree.index(item_id) == target_index:
                return
            listing_tree.move(item_id, "", target_index)
            listing_tree.selection_set(item_id)
            listing_tree.focus(item_id)
            sync_artworks_from_tree()
            mark_order_changed()

        def move_selected(direction):
            sel = listing_tree.selection()
            if not sel:
                messagebox.showwarning("No Selection", "Select a listing to move.", parent=win)
                return
            item_id = sel[0]
            new_index = listing_tree.index(item_id) + direction
            if new_index < 0 or new_index >= len(listing_tree.get_children("")):
                return
            move_item(item_id, new_index)

        drag_state = {"item": None}

        def start_drag(event):
            item_id = listing_tree.identify_row(event.y)
            if not item_id:
                drag_state["item"] = None
                return
            drag_state["item"] = item_id
            listing_tree.selection_set(item_id)
            listing_tree.focus(item_id)

        def drag_row(event):
            item_id = drag_state.get("item")
            target_id = listing_tree.identify_row(event.y)
            if not item_id or not target_id or item_id == target_id:
                return
            move_item(item_id, listing_tree.index(target_id))

        def end_drag(_event=None):
            drag_state["item"] = None

        def save_order():
            order_ids = current_order_ids()
            if not order_ids:
                return
            focus_id = selected["art"].get("id") if selected["art"] else None
            try:
                refreshed_artworks = self._save_artwork_order(order_ids)
                refresh_listing_tree(refreshed_artworks, focus_id=focus_id)
                status.config(text="Saved website listing order.")
            except Exception as exc:
                messagebox.showerror("Save Order Failed", str(exc), parent=win)

        listing_tree.bind("<<TreeviewSelect>>", on_select)
        listing_tree.bind("<ButtonPress-1>", start_drag)
        listing_tree.bind("<B1-Motion>", drag_row)
        listing_tree.bind("<ButtonRelease-1>", end_drag)
        order_buttons = ttk.Frame(left)
        order_buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(order_buttons, text="Move Up", command=lambda: move_selected(-1)).pack(side=tk.LEFT)
        ttk.Button(order_buttons, text="Move Down", command=lambda: move_selected(1)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(order_buttons, text="Save Order", command=save_order, style="Success.TButton").pack(side=tk.RIGHT)
        buttons = ttk.Frame(right)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Generate Description", command=generate, style="Accent.TButton").pack(side=tk.LEFT)
        ttk.Button(buttons, text="Add Images", command=add_images).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Save Changes", command=save, style="Success.TButton").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Delete Listing", command=delete_listing, style="Danger.TButton").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side=tk.RIGHT)
        first = str(artworks[0].get("id"))
        listing_tree.selection_set(first)
        listing_tree.focus(first)
        populate(artworks[0])


def main():
    root = tk.Tk()
    ArtCatalogAppWithDelete(root)
    root.mainloop()


if __name__ == "__main__":
    main()
