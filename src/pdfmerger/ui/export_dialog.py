"""Choose quality, optimization and security options for the exported PDF."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QRadioButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..core.quality import (PRESET_ORDER, EncryptionOptions, ExportOptions, apply_preset,
                            detect_preset)


class ExportDialog(QDialog):
    def __init__(self, opts: ExportOptions, total_pages: int, selected_pages: int,
                 selection_only: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export PDF"))
        self._updating = False
        lay = QVBoxLayout(self)

        # ---- pages ----
        g_pages = QGroupBox(self.tr("Pages"))
        hp = QHBoxLayout(g_pages)
        self.rb_all = QRadioButton(self.tr("All pages ({0})").format(total_pages))
        self.rb_sel = QRadioButton(self.tr("Selected pages only ({0})").format(selected_pages))
        self.rb_sel.setEnabled(selected_pages > 0)
        (self.rb_sel if selection_only and selected_pages else self.rb_all).setChecked(True)
        hp.addWidget(self.rb_all)
        hp.addWidget(self.rb_sel)
        hp.addStretch()
        lay.addWidget(g_pages)

        # ---- quality ----
        g_q = QGroupBox(self.tr("Image quality"))
        fq = QFormLayout(g_q)
        self.preset = QComboBox()
        names = {
            "original": self.tr("Original (keep images untouched)"),
            "print": self.tr("Print – 300 dpi, high quality"),
            "ebook": self.tr("eBook – 150 dpi, medium quality"),
            "screen": self.tr("Screen – 72 dpi, smallest file"),
            "custom": self.tr("Custom"),
        }
        for key in PRESET_ORDER:
            self.preset.addItem(names[key], key)
        fq.addRow(self.tr("Preset:"), self.preset)

        self.cb_down = QCheckBox(self.tr("Downsample images to"))
        self.sp_dpi = QSpinBox(suffix=" dpi", minimum=36, maximum=1200, singleStep=12)
        self.sp_thr = QSpinBox(suffix=" dpi", minimum=37, maximum=2400, singleStep=12)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.sp_dpi)
        h.addWidget(QLabel(self.tr("when above")))
        h.addWidget(self.sp_thr)
        h.addStretch()
        fq.addRow(self.cb_down, row)

        self.cb_jpeg = QCheckBox(self.tr("Recompress as JPEG, quality"))
        self.sl_q = QSlider(Qt.Orientation.Horizontal, minimum=10, maximum=100)
        self.lb_q = QLabel()
        self.lb_q.setMinimumWidth(30)
        row2 = QWidget()
        h2 = QHBoxLayout(row2)
        h2.setContentsMargins(0, 0, 0, 0)
        h2.addWidget(self.sl_q, 1)
        h2.addWidget(self.lb_q)
        fq.addRow(self.cb_jpeg, row2)
        self.cb_lossless = QCheckBox(self.tr("Also convert lossless images (PNG-like) to JPEG"))
        self.cb_bitonal = QCheckBox(self.tr("Include black && white (scanned text) images"))
        fq.addRow(self.cb_lossless)
        fq.addRow(self.cb_bitonal)
        lay.addWidget(g_q)

        # ---- lossless optimization ----
        g_o = QGroupBox(self.tr("Lossless optimization"))
        fo = QFormLayout(g_o)
        self.cmb_garbage = QComboBox()
        for lvl, txt in enumerate([self.tr("None"), self.tr("Remove unused objects"),
                                   self.tr("… and compact the cross-reference table"),
                                   self.tr("… and merge duplicate objects"),
                                   self.tr("… and merge duplicate streams (slowest)")]):
            self.cmb_garbage.addItem(f"{lvl} – {txt}", lvl)
        fo.addRow(self.tr("Clean-up level:"), self.cmb_garbage)
        self.cb_deflate = QCheckBox(self.tr("Compress uncompressed streams"))
        self.cb_deflate_img = QCheckBox(self.tr("Compress uncompressed images"))
        self.cb_deflate_fonts = QCheckBox(self.tr("Compress uncompressed fonts"))
        self.cb_objstms = QCheckBox(self.tr("Use object streams (smaller file, PDF 1.5+)"))
        self.cb_clean = QCheckBox(self.tr("Sanitize page content streams"))
        for cb in (self.cb_deflate, self.cb_deflate_img, self.cb_deflate_fonts, self.cb_objstms,
                   self.cb_clean):
            fo.addRow(cb)
        lay.addWidget(g_o)

        # ---- content ----
        g_c = QGroupBox(self.tr("Content"))
        vc = QVBoxLayout(g_c)
        self.cb_sanitize = QCheckBox(self.tr(
            "Remove links, form fields, JavaScript, attachments and XMP metadata"))
        self.cb_sanitize.setToolTip(self.tr(
            "Recommended when the input files come from untrusted sources."))
        vc.addWidget(self.cb_sanitize)
        lay.addWidget(g_c)

        # ---- security ----
        self.g_s = QGroupBox(self.tr("Protect with password (AES-256)"))
        self.g_s.setCheckable(True)
        fs = QFormLayout(self.g_s)
        self.ed_user = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.ed_user.setPlaceholderText(self.tr("Required to open the document"))
        self.ed_owner = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.ed_owner.setPlaceholderText(self.tr("Leave empty to generate a random one"))
        fs.addRow(self.tr("Open password:"), self.ed_user)
        fs.addRow(self.tr("Permissions password:"), self.ed_owner)
        self.cb_print = QCheckBox(self.tr("Allow printing"))
        self.cb_copy = QCheckBox(self.tr("Allow copying text and images"))
        self.cb_modify = QCheckBox(self.tr("Allow modifying"))
        self.cb_annot = QCheckBox(self.tr("Allow comments and form filling"))
        perm = QWidget()
        hperm = QHBoxLayout(perm)
        hperm.setContentsMargins(0, 0, 0, 0)
        v1, v2 = QVBoxLayout(), QVBoxLayout()
        v1.addWidget(self.cb_print)
        v1.addWidget(self.cb_copy)
        v2.addWidget(self.cb_modify)
        v2.addWidget(self.cb_annot)
        hperm.addLayout(v1)
        hperm.addLayout(v2)
        fs.addRow(perm)
        lay.addWidget(self.g_s)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_export = bb.addButton(self.tr("Export…"), QDialogButtonBox.ButtonRole.AcceptRole)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self._load(opts)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        for w in (self.cb_down, self.cb_jpeg, self.cb_lossless, self.cb_bitonal):
            w.toggled.connect(self._custom_changed)
        for w in (self.sp_dpi, self.sp_thr, self.sl_q):
            w.valueChanged.connect(self._custom_changed)
        self.sl_q.valueChanged.connect(lambda v: self.lb_q.setText(str(v)))
        self.sp_dpi.valueChanged.connect(self._dpi_changed)

    # ---- state <-> widgets ----------------------------------------------
    def _load(self, o: ExportOptions) -> None:
        self._updating = True
        self.cb_down.setChecked(o.downsample)
        self.sp_dpi.setValue(o.dpi_target)
        self.sp_thr.setValue(o.dpi_threshold)
        self.cb_jpeg.setChecked(o.recompress)
        self.sl_q.setValue(o.jpeg_quality)
        self.lb_q.setText(str(o.jpeg_quality))
        self.cb_lossless.setChecked(o.include_lossless_images)
        self.cb_bitonal.setChecked(o.include_bitonal_images)
        self.cmb_garbage.setCurrentIndex(max(0, min(4, o.garbage)))
        self.cb_deflate.setChecked(o.deflate)
        self.cb_deflate_img.setChecked(o.deflate_images)
        self.cb_deflate_fonts.setChecked(o.deflate_fonts)
        self.cb_objstms.setChecked(o.use_objstms)
        self.cb_clean.setChecked(o.clean)
        self.cb_sanitize.setChecked(o.sanitize)
        enc = o.encryption or EncryptionOptions()
        self.g_s.setChecked(o.encryption is not None)
        self.ed_user.setText(enc.user_password)
        self.ed_owner.setText(enc.owner_password)
        self.cb_print.setChecked(enc.allow_print)
        self.cb_copy.setChecked(enc.allow_copy)
        self.cb_modify.setChecked(enc.allow_modify)
        self.cb_annot.setChecked(enc.allow_annotate)
        self.preset.setCurrentIndex(PRESET_ORDER.index(detect_preset(o)))
        self._update_enabled()
        self._updating = False

    def options(self) -> ExportOptions:
        enc = None
        if self.g_s.isChecked():
            enc = EncryptionOptions(self.ed_user.text(), self.ed_owner.text(),
                                    self.cb_print.isChecked(), self.cb_copy.isChecked(),
                                    self.cb_modify.isChecked(), self.cb_annot.isChecked())
        return ExportOptions(
            downsample=self.cb_down.isChecked(), dpi_target=self.sp_dpi.value(),
            dpi_threshold=self.sp_thr.value(), recompress=self.cb_jpeg.isChecked(),
            jpeg_quality=self.sl_q.value(), include_lossless_images=self.cb_lossless.isChecked(),
            include_bitonal_images=self.cb_bitonal.isChecked(),
            garbage=self.cmb_garbage.currentData(), deflate=self.cb_deflate.isChecked(),
            deflate_images=self.cb_deflate_img.isChecked(),
            deflate_fonts=self.cb_deflate_fonts.isChecked(), clean=self.cb_clean.isChecked(),
            use_objstms=self.cb_objstms.isChecked(), sanitize=self.cb_sanitize.isChecked(),
            encryption=enc)

    def selection_only(self) -> bool:
        return self.rb_sel.isChecked()

    # ---- reactions ---------------------------------------------------------
    def _update_enabled(self) -> None:
        self.sp_dpi.setEnabled(self.cb_down.isChecked())
        self.sp_thr.setEnabled(self.cb_down.isChecked())
        self.sl_q.setEnabled(self.cb_jpeg.isChecked())
        any_rewrite = self.cb_down.isChecked() or self.cb_jpeg.isChecked()
        self.cb_lossless.setEnabled(any_rewrite)
        self.cb_bitonal.setEnabled(any_rewrite)

    def _preset_changed(self) -> None:
        if self._updating:
            return
        key = self.preset.currentData()
        if key != "custom":
            self._load(apply_preset(self.options(), key))

    def _dpi_changed(self, v: int) -> None:
        if not self._updating and self.sp_thr.value() <= v:
            self.sp_thr.setValue(int(v * 1.5))

    def _custom_changed(self) -> None:
        self._update_enabled()
        if self._updating:
            return
        self._updating = True
        self.preset.setCurrentIndex(PRESET_ORDER.index(detect_preset(self.options())))
        self._updating = False

    def _accept(self) -> None:
        if self.g_s.isChecked() and not (self.ed_user.text() or self.ed_owner.text()):
            QMessageBox.warning(self, self.windowTitle(),
                                self.tr("Enter at least one password, or turn off password protection."))
            return
        self.accept()
