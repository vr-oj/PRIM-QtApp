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
)


class GLViewfinder(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._texture = None
        self._img_size = QSize(0, 0)
        self._pending_qimg = None  # QImage pending upload
        self.prog = None
        self.vao = None
        self.vbo = None
        self.ctx = None

    def initializeGL(self):
        # Acquire GL function pointers
        self.ctx = self.context().functions()

        # Shader program setup (vertex + fragment)
        self.prog = QOpenGLShaderProgram(self)
        # TODO: compile & link shaders

        # Vertex Array & Buffer init
        self.vao = QOpenGLVertexArrayObject(self)
        self.vao.create()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vbo.create()
        # TODO: bind VBO, upload vertices, configure attributes

        # Clear color
        self.ctx.glClearColor(0.0, 0.0, 0.0, 1.0)

    def update_frame(self, qimg: QImage):
        """
        Store the incoming QImage (converted to RGBA8888) for GPU upload.
        """
        if qimg.isNull():
            return
        # Convert once for consistency
        self._pending_qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
        self._img_size = self._pending_qimg.size()
        self.update()  # trigger paintGL

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

        # Bind and (re)allocate storage if size/format changed
        self._texture.bind()
        current_format = QOpenGLTexture.RGBA8_UNorm
        if (
            self._texture.width() != w
            or self._texture.height() != h
            or self._texture.format() != current_format
        ):
            self._texture.setSize(w, h)
            self._texture.setFormat(current_format)
            self._texture.allocateStorage(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8)

        # Upload the QImage
        self._texture.setData(
            self._pending_qimg,
            QOpenGLTexture.MipMapGeneration.NoMipmapGeneration,
        )
        # Clear pending image
        self._pending_qimg = None

        # Clear screen and draw
        self.ctx.glClear(self.ctx.GL_COLOR_BUFFER_BIT)
        if self.prog and self.vao:
            self.prog.bind()
            self.vao.bind()
            self.ctx.glDrawArrays(self.ctx.GL_TRIANGLE_STRIP, 0, 4)
            self.vao.release()
            self.prog.release()

        self._texture.release()

    def resizeGL(self, w: int, h: int):
        if self.ctx:
            self.ctx.glViewport(0, 0, w, h)
