# gl_viewfinder.py
import numpy as np
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture, QImage
from OpenGL import GL


class GLViewfinder(QOpenGLWidget):
    """
    High-performance OpenGL viewfinder widget.
    Receives raw numpy frames and renders them via GPU texture.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.texture = None
        self._frame_data = None
        # Incoming format: numpy array (H x W x C) with either 1 or 3 channels
        self.setMinimumSize(320, 240)

    def initializeGL(self):
        # Initialize OpenGL context and compile shaders
        self.initializeOpenGLFunctions()
        GL.glEnable(GL.GL_TEXTURE_2D)

        # Simple vertex + fragment shaders
        vert_src = b"""
        #version 330 core
        in vec2 position;
        in vec2 texcoord;
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

        # Compile shader program
        self.program = QOpenGLShaderProgram(self.context())
        self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vert_src)
        self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, frag_src)
        self.program.link()

        # Create a placeholder texture
        self.texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self.texture.setMinificationFilter(QOpenGLTexture.Linear)
        self.texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self.texture.setWrapMode(QOpenGLTexture.ClampToEdge)

    def resizeGL(self, w: int, h: int):
        GL.glViewport(0, 0, w, h)

    @pyqtSlot(QImage, object)
    def update_frame(self, frame: np.ndarray):
        """
        Slot to receive raw numpy frame (H x W x C or H x W) from SDKCameraThread.
        Uploads data to the GPU texture and triggers a repaint.
        """
        # Determine format
        h, w = frame.shape[:2]
        channels = frame.shape[2] if frame.ndim == 3 else 1

        # Initialize texture storage if size changed
        if (
            (self.texture.width() != w)
            or (self.texture.height() != h)
            or (self.texture.format() != QOpenGLTexture.RGBA8)
        ):
            internal_format = QOpenGLTexture.RGBA8
            gl_format = GL.GL_RGBA
            gl_type = GL.GL_UNSIGNED_BYTE
            # Allocate texture storage
            self.texture.setSize(w, h)
            self.texture.setFormat(internal_format)
            self.texture.allocateStorage()

        # Prepare RGBA data buffer
        if channels == 3:
            # BGR or RGB -> RGBA
            rgba = np.empty((h, w, 4), dtype=np.uint8)
            rgba[..., :3] = frame[..., ::-1]  # BGR->RGB
            rgba[..., 3] = 255
        else:
            # Mono -> replicate and alpha
            rgba = np.empty((h, w, 4), dtype=np.uint8)
            rgba[..., :3] = frame[..., np.newaxis]
            rgba[..., 3] = 255

        # Upload to GPU
        self.texture.bind()
        self.texture.setData(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8, rgba)
        self.texture.release()
        # Trigger repaint
        self.update()

    def paintGL(self):
        if not self.program or not self.texture:
            return

        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        self.program.bind()
        self.texture.bind()

        # Setup simple quad covering the screen
        # position and texcoord attributes assumed at location 0 and 1
        quad_verts = np.array(
            [
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

        # Enable and feed arrays
        loc_pos = self.program.attributeLocation("position")
        loc_tex = self.program.attributeLocation("texcoord")
        GL.glEnableVertexAttribArray(loc_pos)
        GL.glEnableVertexAttribArray(loc_tex)
        GL.glVertexAttribPointer(
            loc_pos, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, quad_verts.ctypes
        )
        GL.glVertexAttribPointer(
            loc_tex, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, quad_verts.ctypes + 8
        )

        # Draw quad
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

        # Cleanup
        GL.glDisableVertexAttribArray(loc_pos)
        GL.glDisableVertexAttribArray(loc_tex)
        self.texture.release()
        self.program.release()
