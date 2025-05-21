# gl_viewfinder.py
import sys
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import (
    QImage,
    QOpenGLTexture,
    QOpenGLShaderProgram,
    QOpenGLBuffer,
    QOpenGLVertexArrayObject,
    QOpenGLFunctions,
)


class GLViewfinder(QOpenGLWidget, QOpenGLFunctions):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._texture = None
        self._img_size = QSize(0, 0)
        self._pending_qimg = None  # QImage pending upload
        self.prog = None
        self.vao = None
        self.vbo = None

    def initializeGL(self):
        # Initialize OpenGL function resolution
        self.initializeOpenGLFunctions()
        self.ctx = self  # QOpenGLFunctions methods on self

        # Shader program setup (vertex + fragment shaders)
        self.prog = QOpenGLShaderProgram(self)
        # TODO: add shader compilation & linking here

        # Vertex Array & Buffer setup
        self.vao = QOpenGLVertexArrayObject(self)
        self.vao.create()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vbo.create()
        # TODO: bind VBO, upload vertex data, configure vertex attributes

        # Set clear color
        self.ctx.glClearColor(0.0, 0.0, 0.0, 1.0)

    def update_frame(self, qimg: QImage):
        """
        Called from another thread via signal. Stores a converted QImage
        for later upload in paintGL(), and schedules a repaint.
        """
        if qimg.isNull():
            return
        # Convert to RGBA8888 for direct GPU upload
        self._pending_qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
        self._img_size = self._pending_qimg.size()
        self.update()  # Schedule paintGL

    def paintGL(self):
        if not self._pending_qimg:
            return

        w, h = self._img_size.width(), self._img_size.height()

        # Lazy texture creation
        if not self._texture or not self._texture.isCreated():
            self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
            self._texture.create()
            self._texture.setMinificationFilter(QOpenGLTexture.Linear)
            self._texture.setMagnificationFilter(QOpenGLTexture.Linear)
            # self._texture.setWrapMode(QOpenGLTexture.ClampToEdge)

        # Bind and (re)allocate if size/format changed
        self._texture.bind()
        current_format = QOpenGLTexture.RGBA8_UNorm
        if (
            self._texture.width() != w
            or self._texture.height() != h
            or self._texture.format() != current_format
        ):
            self._texture.setSize(w, h)
            self._texture.setFormat(current_format)
            self._texture.allocateStorage(
                QOpenGLTexture.RGBA,
                QOpenGLTexture.UInt8,
            )

        # Upload QImage data with no mipmaps
        self._texture.setData(
            self._pending_qimg,
            QOpenGLTexture.MipMapGeneration.NoMipmapGeneration,
        )
        # Clear pending after upload
        self._pending_qimg = None

        # Render quad
        self.ctx.glClear(self.ctx.GL_COLOR_BUFFER_BIT)
        if self.prog and self.vao:
            self.prog.bind()
            self.vao.bind()
            self.ctx.glDrawArrays(self.ctx.GL_TRIANGLE_STRIP, 0, 4)
            self.vao.release()
            self.prog.release()

        self._texture.release()

    def resizeGL(self, w: int, h: int):
        self.ctx.glViewport(0, 0, w, h)
