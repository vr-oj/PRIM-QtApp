# prim_app/ui/canvas/gl_viewfinder.py
import numpy as np
from PyQt5.QtWidgets import (
    QOpenGLWidget,
    QSizePolicy,
)  # Make sure QSizePolicy is imported
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import (
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QImage,
)
from OpenGL import GL
import logging

log = logging.getLogger(__name__)


class GLViewfinder(QOpenGLWidget):
    """
    High-performance OpenGL viewfinder widget.
    Receives raw numpy frames and renders them via GPU texture, maintaining aspect ratio.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.texture = None
        self.vbo_quad = None

        # Encourage the widget to expand and fill available space
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)  # Maintain a reasonable minimum size

        self.current_frame_width = 0
        self.current_frame_height = 0
        self.frame_aspect_ratio = 1.0  # Default aspect ratio (width / height)

    def initializeGL(self):
        vert_src = b"""
        #version 330 core
        layout (location = 0) in vec2 position;
        layout (location = 1) in vec2 texcoord;
        out vec2 v_texcoord;
        void main() {
            gl_Position = vec4(position, 0.0, 1.0);
            v_texcoord = texcoord;
        }
        """
        frag_src_mono = b""" // Shader for single channel (e.g., R8_UNorm)
        #version 330 core
        uniform sampler2D tex;
        in vec2 v_texcoord;
        out vec4 fragColor;
        void main() {
            float intensity = texture(tex, v_texcoord).r; // Sample red channel
            fragColor = vec4(intensity, intensity, intensity, 1.0); // Display as grayscale
        }
        """
        # You might need a different fragment shader for color images if you support them later
        # For now, assuming Mono8 is the primary format from your camera.
        # If you also get BGR, you'd need to switch shaders or use a universal one.
        # Let's keep it simple for Mono8 first with frag_src_mono.
        # If your previous RGBA8_UNorm approach worked for mono, the original frag_src was okay
        # but R8_UNorm is more efficient for mono data.

        self.program = QOpenGLShaderProgram(self.context())
        if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vert_src):
            log.error(
                f"GLViewfinder: Vertex shader compilation error: {self.program.log()}"
            )
            return
        # Using the mono-specific fragment shader
        if not self.program.addShaderFromSourceCode(
            QOpenGLShader.Fragment, frag_src_mono
        ):  # Using frag_src_mono
            log.error(
                f"GLViewfinder: Fragment shader compilation error: {self.program.log()}"
            )
            return
        if not self.program.link():
            log.error(f"GLViewfinder: Shader link error: {self.program.log()}")
            return

        self.texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self.texture.setMinificationFilter(QOpenGLTexture.Linear)
        self.texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self.texture.setWrapMode(QOpenGLTexture.ClampToEdge)

        quad_verts = np.array(
            [
                -1.0,
                -1.0,
                0.0,
                1.0,  # Bottom-left Pos, Tex
                1.0,
                -1.0,
                1.0,
                1.0,  # Bottom-right Pos, Tex
                -1.0,
                1.0,
                0.0,
                0.0,  # Top-left Pos, Tex
                1.0,
                1.0,
                1.0,
                0.0,  # Top-right Pos, Tex
            ],
            dtype=np.float32,
        )

        self.makeCurrent()
        self.vbo_quad = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, GL.GL_STATIC_DRAW
        )
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.doneCurrent()

    def resizeGL(self, w: int, h: int):
        # The actual viewport adjustment for aspect ratio is done in paintGL.
        # This method is called by Qt when the widget resizes.
        # The QOpenGLWidget base class handles basic setup like making context current.
        # We don't need to explicitly set glViewport here to the full widget size
        # if paintGL is going to override it for aspect ratio.
        # log.debug(f"GLViewfinder resizeGL: w={w}, h={h}")
        super().resizeGL(w, h)  # Call base implementation

    @pyqtSlot(QImage, object)
    def update_frame(self, qimage_unused: QImage, frame: np.ndarray):
        if frame is None or not self.isValid():
            return

        self.makeCurrent()

        h, w = frame.shape[:2]
        channels = frame.shape[2] if frame.ndim == 3 else 1

        # Calculate and store frame aspect ratio
        current_aspect_ratio = w / h if h > 0 else 1.0
        if (
            abs(self.frame_aspect_ratio - current_aspect_ratio) > 1e-5
        ):  # Update if changed
            self.frame_aspect_ratio = current_aspect_ratio
            # A repaint will be triggered by self.update() later anyway

        # Texture reallocation if size or format changes (especially if supporting color later)
        # For now, assuming Mono8, so format won't change often after first frame.
        if (
            not self.texture.isCreated()
            or self.current_frame_width != w
            or self.current_frame_height != h
        ):
            if self.texture.isCreated():
                self.texture.destroy()

            self.texture.create()
            self.texture.setSize(w, h)

            # Optimized for Mono8 (single channel) data
            # If you later support color (e.g., BGR), you'll need to adjust this
            # and potentially the fragment shader.
            internal_texture_format = (
                QOpenGLTexture.R8_UNorm
            )  # For single channel 8-bit data

            self.texture.setFormat(internal_texture_format)
            self.texture.allocateStorage()  # Allocate based on setSize and setFormat
            self.current_frame_width = w
            self.current_frame_height = h
            log.debug(
                f"GLViewfinder: Texture re(allocated) for {w}x{h}, aspect: {self.frame_aspect_ratio:.2f}"
            )

        data_for_texture = frame
        # For R8_UNorm internal format, the source data should be single channel
        source_pixel_format = (
            QOpenGLTexture.Red
        )  # Source data is treated as the Red channel

        if channels == 1:
            if frame.ndim == 3 and frame.shape[2] == 1:  # If HxWx1
                data_for_texture = frame[
                    :, :, 0
                ].copy()  # Make it 2D HxW, ensure it's contiguous
            elif frame.ndim == 2:  # Already HxW
                data_for_texture = frame.copy()  # Ensure it's contiguous for safety
            # else: error, should be 2D or HxWx1 for single channel
        # elif channels == 3: # Example if you add BGR support later
        # source_pixel_format = QOpenGLTexture.BGR
        # internal_texture_format would need to be BGR8_UNorm or RGB8_UNorm
        # data_for_texture = frame.copy()
        else:
            log.warning(
                f"GLViewfinder: Unsupported number of channels ({channels}) for current setup (expected 1 for Mono8)."
            )
            self.doneCurrent()
            return

        if data_for_texture is not None:
            self.texture.bind()
            # Upload data: source format is Red, source type is UInt8 (for numpy uint8 array)
            self.texture.setData(
                source_pixel_format, QOpenGLTexture.UInt8, data_for_texture.data
            )
            self.texture.release()
            self.update()  # Request a repaint (calls paintGL)

        self.doneCurrent()

    def paintGL(self):
        if (
            not self.isValid()
            or not self.program
            or not self.program.isLinked()
            or not self.texture
            or not self.texture.isCreated()
            or self.vbo_quad is None
            or self.current_frame_width == 0  # Ensure we have valid frame dimensions
            or self.current_frame_height == 0
        ):
            return

        self.makeCurrent()

        # Set clear color (e.g., black for letterbox/pillarbox bars)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)  # Changed to black
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        widget_w = self.width()
        widget_h = self.height()

        if (
            widget_w == 0 or widget_h == 0
        ):  # Avoid division by zero if widget not yet sized
            self.doneCurrent()
            return

        widget_aspect = widget_w / widget_h

        # Calculate viewport to maintain frame's aspect ratio
        vp_x, vp_y, vp_w, vp_h = 0, 0, widget_w, widget_h

        if self.frame_aspect_ratio > widget_aspect:
            # Frame is wider than widget display area (needs letterboxing: کاهش ارتفاع دید)
            # Scale viewport height according to frame aspect ratio relative to widget width
            vp_h = int(widget_w / self.frame_aspect_ratio)
            vp_y = int((widget_h - vp_h) / 2)  # Center vertically
        elif self.frame_aspect_ratio < widget_aspect:
            # Frame is taller than widget display area (needs pillarboxing: کاهش عرض دید)
            # Scale viewport width according to frame aspect ratio relative to widget height
            vp_w = int(widget_h * self.frame_aspect_ratio)
            vp_x = int((widget_w - vp_w) / 2)  # Center horizontally
        # Else: aspect ratios match, use full widget_w, widget_h

        GL.glViewport(vp_x, vp_y, vp_w, vp_h)  # Apply the calculated viewport

        if not self.program.bind():
            log.error("paintGL: Failed to bind shader program.")
            # Reset viewport to full on error to avoid unexpected clipping if paintGL is called again
            GL.glViewport(0, 0, widget_w, widget_h)
            self.doneCurrent()
            return

        GL.glActiveTexture(GL.GL_TEXTURE0)
        self.texture.bind()
        self.program.setUniformValue("tex", 0)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        stride = 4 * np.dtype(np.float32).itemsize
        pos_loc = self.program.attributeLocation("position")
        tex_loc = self.program.attributeLocation("texcoord")

        if pos_loc != -1:
            GL.glEnableVertexAttribArray(pos_loc)
            GL.glVertexAttribPointer(
                pos_loc, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, GL.ctypes.c_void_p(0)
            )

        if tex_loc != -1:
            GL.glEnableVertexAttribArray(tex_loc)
            GL.glVertexAttribPointer(
                tex_loc,
                2,
                GL.GL_FLOAT,
                GL.GL_FALSE,
                stride,
                GL.ctypes.c_void_p(2 * np.dtype(np.float32).itemsize),
            )

        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

        if pos_loc != -1:
            GL.glDisableVertexAttribArray(pos_loc)
        if tex_loc != -1:
            GL.glDisableVertexAttribArray(tex_loc)

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self.texture.release()
        self.program.release()

        # After drawing with the aspect-corrected viewport,
        # some applications reset the viewport to the full widget size if other UI elements
        # are drawn directly with OpenGL in the same paintGL call. For a dedicated viewfinder, it might not be strictly necessary.
        # However, Qt might do further painting, so it's good practice to reset if unsure.
        # For now, let's assume this widget is the only thing drawing in its paintGL.
        # If you add overlays or other GL drawing, you might need: GL.glViewport(0, 0, widget_w, widget_h)

        self.doneCurrent()
