# prim_app/ui/canvas/gl_viewfinder.py
import numpy as np
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import (
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QImage,
    QOpenGLFunctions,
)
from OpenGL import GL


class GLViewfinder(QOpenGLWidget, QOpenGLFunctions):
    """
    High-performance OpenGL viewfinder widget.
    Receives raw numpy frames and renders them via GPU texture.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.texture = None
        self.vbo_quad = None  # For vertex buffer object
        self._frame_data = None
        self.setMinimumSize(320, 240)

    def initializeGL(self):
        self.initializeOpenGLFunctions()  # Initialize QOpenGLFunctions
        # GL.glEnable(GL.GL_TEXTURE_2D) # Not strictly needed with modern shaders using samplers

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
        frag_src = b"""
        #version 330 core
        uniform sampler2D tex;
        in vec2 v_texcoord;
        out vec4 fragColor;
        void main() {
            fragColor = texture(tex, v_texcoord);
        }
        """

        self.program = QOpenGLShaderProgram(self.context())
        self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vert_src)
        self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, frag_src)
        if not self.program.link():
            print(f"Shader link error: {self.program.log()}")
            return
        if not self.program.bind():
            print(f"Shader bind error: {self.program.log()}")
            return

        # Create and configure texture object
        self.texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self.texture.setMinificationFilter(QOpenGLTexture.Linear)
        self.texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self.texture.setWrapMode(QOpenGLTexture.ClampToEdge)
        # Texture format and allocation will be handled in update_frame when frame size is known

        # Setup VBO for a quad
        quad_verts = np.array(
            [
                # Positions  Texture Coords
                -1.0,
                -1.0,
                0.0,
                1.0,
                1.0,
                -1.0,
                1.0,
                1.0,
                -1.0,
                1.0,
                0.0,
                0.0,
                1.0,
                1.0,
                1.0,
                0.0,
            ],
            dtype=np.float32,
        )

        self.vbo_quad = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, GL.GL_STATIC_DRAW
        )
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)  # Unbind

        self.program.release()

    def resizeGL(self, w: int, h: int):
        GL.glViewport(0, 0, w, h)

    @pyqtSlot(QImage, object)
    def update_frame(self, qimage: QImage, frame: np.ndarray):  # CORRECTED SIGNATURE
        """
        Slot to receive raw numpy frame (H x W x C or H x W) from SDKCameraThread.
        Uploads data to the GPU texture and triggers a repaint.
        'qimage' is received to match signal, 'frame' (numpy array) is used for texture.
        """
        if frame is None or not self.texture:
            return

        h, w = frame.shape[:2]
        channels = frame.shape[2] if frame.ndim == 3 else 1

        if (
            not self.texture.isCreated()
            or self.texture.width() != w
            or self.texture.height() != h
        ):  # Check if texture needs reallocation
            if self.texture.isCreated():
                self.texture.destroy()

            self.texture.create()
            self.texture.setSize(w, h)
            # For QOpenGLTexture.setData with sourceFormat=QOpenGLTexture.RGBA and sourceType=QOpenGLTexture.UInt8,
            # the internal format could be QOpenGLTexture.RGBA8_UNorm.
            self.texture.setFormat(
                QOpenGLTexture.RGBA8_UNorm
            )  # Common format for 8-bit RGBA
            self.texture.allocateStorage(
                QOpenGLTexture.RGBA, QOpenGLTexture.UInt8
            )  # Pixel data is RGBA, UInt8

        # Prepare RGBA data buffer
        rgba = np.empty((h, w, 4), dtype=np.uint8)
        if channels == 3:  # Assuming BGR input from OpenCV
            rgba[..., 0] = frame[..., 2]  # R
            rgba[..., 1] = frame[..., 1]  # G
            rgba[..., 2] = frame[..., 0]  # B
            rgba[..., 3] = 255  # A
        elif channels == 1:  # Grayscale
            rgba[..., 0] = frame  # R
            rgba[..., 1] = frame  # G
            rgba[..., 2] = frame  # B
            rgba[..., 3] = 255  # A
        else:
            print(f"GLViewfinder: Unsupported number of channels ({channels})")
            return

        self.texture.bind()
        self.texture.setData(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8, rgba)
        self.texture.release()
        self.update()  # Request a repaint

    def paintGL(self):
        if (
            not self.program
            or not self.program.isLinked()
            or not self.texture
            or not self.texture.isCreated()
            or self.vbo_quad is None
        ):
            return

        GL.glClearColor(0.1, 0.1, 0.1, 1.0)  # Dark grey background
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        if not self.program.bind():
            return

        # Bind texture to texture unit 0
        GL.glActiveTexture(GL.GL_TEXTURE0)
        self.texture.bind()
        self.program.setUniformValue(
            "tex", 0
        )  # Shader sampler 'tex' uses texture unit 0

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo_quad)

        pos_loc = self.program.attributeLocation("position")
        tex_loc = self.program.attributeLocation("texcoord")

        if pos_loc != -1:
            GL.glEnableVertexAttribArray(pos_loc)
            GL.glVertexAttribPointer(
                pos_loc,
                2,
                GL.GL_FLOAT,
                GL.GL_FALSE,
                4 * np.dtype(np.float32).itemsize,
                GL.ctypes.c_void_p(0),
            )

        if tex_loc != -1:
            GL.glEnableVertexAttribArray(tex_loc)
            GL.glVertexAttribPointer(
                tex_loc,
                2,
                GL.GL_FLOAT,
                GL.GL_FALSE,
                4 * np.dtype(np.float32).itemsize,
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
