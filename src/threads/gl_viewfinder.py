# gl_viewfinder.py
import numpy as np
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QImage
from PyQt5.QtGui import QOpenGLTexture, QOpenGLShader, QOpenGLShaderProgram
from PyQt5.QtGui import QOpenGLBuffer, QOpenGLVertexArrayObject
from PyQt5.QtCore import Qt


class GLViewfinder(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._texture = None
        self._img_size = QSize(0, 0)
        self._cpu_buffer = None  # raw bytes

    def update_frame(self, qimg: QImage):
        # copy data into CPU buffer
        self._img_size = qimg.size()
        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        ptr = qimg.constBits()
        ptr.setsize(qimg.byteCount())
        self._cpu_buffer = bytes(ptr)
        self.update()  # schedule paintGL

    def initializeGL(self):
        self.initializeOpenGLFunctions()
        # create a simple shader program to draw textured quad
        vs_src = """
            attribute vec2 pos;
            attribute vec2 tex;
            varying vec2 v_tex;
            void main() {
                gl_Position = vec4(pos, 0.0, 1.0);
                v_tex = tex;
            }
        """
        fs_src = """
            varying vec2 v_tex;
            uniform sampler2D tex;
            void main() {
                gl_FragColor = texture2D(tex, v_tex);
            }
        """
        self.prog = QOpenGLShaderProgram(self.context())
        self.prog.addShaderFromSourceCode(QOpenGLShader.Vertex, vs_src)
        self.prog.addShaderFromSourceCode(QOpenGLShader.Fragment, fs_src)
        self.prog.link()

        # full‐screen quad data
        verts = np.array(
            [
                -1,
                -1,
                0,
                1,
                1,
                -1,
                1,
                1,
                -1,
                1,
                0,
                0,
                1,
                1,
                1,
                0,
            ],
            dtype=np.float32,
        )

        # pack into VBO & VAO
        self.vao = QOpenGLVertexArrayObject(self)
        self.vao.create()
        self.vao.bind()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vbo.create()
        self.vbo.bind()
        self.vbo.allocate(verts.tobytes(), verts.nbytes)

        loc_pos = self.prog.attributeLocation("pos")
        loc_tex = self.prog.attributeLocation("tex")
        self.prog.enableAttributeArray(loc_pos)
        self.prog.setAttributeBuffer(loc_pos, self.ctx.GL_FLOAT, 0, 2, 16)
        self.prog.enableAttributeArray(loc_tex)
        self.prog.setAttributeBuffer(loc_tex, self.ctx.GL_FLOAT, 8, 2, 16)

        self.vbo.release()
        self.vao.release()

        # texture placeholder
        self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        self._texture.setMinificationFilter(QOpenGLTexture.Linear)
        self._texture.setMagnificationFilter(QOpenGLTexture.Linear)

    def paintGL(self):
        if not self._cpu_buffer:
            return
        w, h = self._img_size.width(), self._img_size.height()
        self._texture.bind()
        self._texture.setSize(w, h)
        self._texture.setFormat(QOpenGLTexture.RGB8_UNorm)
        self._texture.allocateStorage()
        self._texture.setData(
            QOpenGLTexture.PixelFormat.RGB,
            QOpenGLTexture.PixelType.UInt8,
            self._cpu_buffer,
        )

        self.ctx.glClear(self.ctx.GL_COLOR_BUFFER_BIT)
        self.prog.bind()
        self.vao.bind()
        self.ctx.glDrawArrays(self.ctx.GL_TRIANGLE_STRIP, 0, 4)
        self.vao.release()
        self.prog.release()
        self._texture.release()

    def resizeGL(self, w: int, h: int):
        self.ctx.glViewport(0, 0, w, h)
