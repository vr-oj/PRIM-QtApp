# gl_viewfinder.py
import sys
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import QSize
from PyQt5.QtGui import (
    QImage,
    QOpenGLTexture,
    QOpenGLShaderProgram,
    QOpenGLBuffer,
    QOpenGLVertexArrayObject,
)
from OpenGL import GL


class GLViewfinder(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._texture = None
        self._img_size = QSize(0, 0)
        self._pending_qimg = None  # QImage pending upload
        self.prog = None
        self.vao = None
        self.vbo = None

    def initializeGL(self):
        # Shader program setup (compile & link yourself)
        self.prog = QOpenGLShaderProgram(self)
        # TODO: compile vertex & fragment shaders into self.prog

        # VAO & VBO setup
        self.vao = QOpenGLVertexArrayObject(self)
        self.vao.create()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vbo.create()
        # TODO: bind VBO, upload vertex data, configure attributes

        # Set clear color
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)

    def update_frame(self, qimg: QImage):
        """
        Store the incoming frame as a QImage for GPU upload in paintGL().
        """
        if qimg.isNull():
            return
        # Convert once for consistent GPU format
        self._pending_qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
        self._img_size = self._pending_qimg.size()
        self.update()  # triggers paintGL

    def paintGL(self):
        if self._pending_qimg is None:
            return

        w, h = self._img_size.width(), self._img_size.height()

        # Lazy texture creation
        if not self._texture or not self._texture.isCreated():
            self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
            self._texture.create()
            self._texture.setMinificationFilter(QOpenGLTexture.Linear)
            self._texture.setMagnificationFilter(QOpenGLTexture.Linear)

        # Bind & allocate if dimensions or format changed
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

        # Upload the image data (no mipmaps)
        self._texture.setData(
            self._pending_qimg,
            QOpenGLTexture.MipMapGeneration.NoMipmapGeneration,
        )
        self._pending_qimg = None

        # Clear and draw
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self.prog and self.vao:
            self.prog.bind()
            self.vao.bind()
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            self.vao.release()
            self.prog.release()

        self._texture.release()

    def resizeGL(self, w: int, h: int):
        GL.glViewport(0, 0, w, h)
