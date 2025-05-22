# gl_viewfinder.py
import sys
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import QSize, QByteArray
from PyQt5.QtGui import (
    QImage,
    QOpenGLTexture,
    QOpenGLShaderProgram,
    QOpenGLBuffer,
    QOpenGLVertexArrayObject,
    QOpenGLShader,
)
from OpenGL import GL
import ctypes  # Needed for vertex data


class GLViewfinder(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._texture = None
        self._img_size = QSize(0, 0)
        self._pending_qimg = None  # QImage pending upload
        self.prog = None
        self.vao = QOpenGLVertexArrayObject()  # Initialize here
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)  # Initialize here
        self.ebo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)  # For drawing with indices

    def initializeGL(self):
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)  # Set clear color first

        # Shader program setup
        self.prog = QOpenGLShaderProgram(self)

        # Vertex Shader
        vs_source = """
            #version 330 core
            layout (location = 0) in vec3 aPos;
            layout (location = 1) in vec2 aTexCoord;
            out vec2 TexCoord;
            void main()
            {
                gl_Position = vec4(aPos.x, aPos.y, aPos.z, 1.0);
                TexCoord = aTexCoord;
            }
        """
        # Fragment Shader - Flips texture coordinates vertically
        fs_source = """
            #version 330 core
            out vec4 FragColor;
            in vec2 TexCoord;
            uniform sampler2D ourTexture;
            void main()
            {
                FragColor = texture(ourTexture, vec2(TexCoord.x, 1.0 - TexCoord.y));
            }
        """

        if not self.prog.addShaderFromSourceCode(QOpenGLShader.Vertex, vs_source):
            print(f"Vertex shader compilation error: {self.prog.log()}")
            return
        if not self.prog.addShaderFromSourceCode(QOpenGLShader.Fragment, fs_source):
            print(f"Fragment shader compilation error: {self.prog.log()}")
            return
        if not self.prog.link():
            print(f"Shader linking error: {self.prog.log()}")
            return

        # VAO & VBO setup
        # x, y, z, s, t (texture coordinates)
        vertices = QByteArray(
            b"\x00\x00\x80\xbf\x00\x00\x80\xbf\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # -1.0, -1.0, 0.0, 0.0, 0.0
            b"\x00\x00\x80\x3f\x00\x00\x80\xbf\x00\x00\x00\x00\x00\x00\x80\x3f\x00\x00\x00\x00"  #  1.0, -1.0, 0.0, 1.0, 0.0
            b"\x00\x00\x80\x3f\x00\x00\x80\x3f\x00\x00\x00\x00\x00\x00\x80\x3f\x00\x00\x80\x3f"  #  1.0,  1.0, 0.0, 1.0, 1.0
            b"\x00\x00\x80\xbf\x00\x00\x80\x3f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x3f"  # -1.0,  1.0, 0.0, 0.0, 1.0
        )
        # Using QByteArray and then converting to `bytes` for `ctypes.string_at` or similar might be more robust
        # For direct use with QOpenGLBuffer, QByteArray can be fine.
        # Raw float data:
        # -1.0, -1.0, 0.0,   0.0, 0.0,  // Bottom Left
        #  1.0, -1.0, 0.0,   1.0, 0.0,  // Bottom Right
        #  1.0,  1.0, 0.0,   1.0, 1.0,  // Top Right
        # -1.0,  1.0, 0.0,   0.0, 1.0   // Top Left
        vertex_data_float = [
            -1.0,
            -1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            -1.0,
            0.0,
            1.0,
            0.0,
            1.0,
            1.0,
            0.0,
            1.0,
            1.0,
            -1.0,
            1.0,
            0.0,
            0.0,
            1.0,
        ]
        vertex_qbytearray = QByteArray()
        for val in vertex_data_float:
            vertex_qbytearray.append(bytes(ctypes.c_float(val)))

        indices = QByteArray(
            b"\x00\x00\x00\x00\x01\x00\x00\x00\x02\x00\x00\x00"  # 0, 1, 2
            b"\x02\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00"  # 2, 3, 0
        )
        # Raw int data:
        # 0, 1, 2,  // First Triangle
        # 2, 3, 0   // Second Triangle
        index_data_int = [0, 1, 2, 2, 3, 0]
        index_qbytearray = QByteArray()
        for val in index_data_int:
            index_qbytearray.append(bytes(ctypes.c_uint(val)))

        if not self.vao.isCreated():
            self.vao.create()
        self.vao.bind()

        if not self.vbo.isCreated():
            self.vbo.create()
        self.vbo.bind()
        self.vbo.allocate(vertex_qbytearray, vertex_qbytearray.size())

        if not self.ebo.isCreated():
            self.ebo.create()
        self.ebo.bind()
        self.ebo.allocate(index_qbytearray, index_qbytearray.size())

        # Position attribute
        self.prog.enableAttributeArray(0)
        self.prog.setAttributeBuffer(
            0, GL.GL_FLOAT, 0, 3, 5 * ctypes.sizeof(ctypes.c_float)
        )
        # Texture coord attribute
        self.prog.enableAttributeArray(1)
        self.prog.setAttributeBuffer(
            1,
            GL.GL_FLOAT,
            3 * ctypes.sizeof(ctypes.c_float),
            2,
            5 * ctypes.sizeof(ctypes.c_float),
        )

        self.vao.release()
        self.vbo.release()
        self.ebo.release()  # Release EBO after VAO is configured
        self.prog.release()

    def update_frame(self, qimg: QImage):
        if qimg.isNull():
            return
        # Convert to a format OpenGL can easily handle, and flip vertically for correct display
        # The fragment shader now handles the flip, so we don't need to do it here.
        self._pending_qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
        self._img_size = self._pending_qimg.size()
        self.update()

    def paintGL(self):
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        if self._pending_qimg is None or self._pending_qimg.isNull():
            # Optionally, draw a black screen or a "waiting" message if no image
            return

        w, h = self._img_size.width(), self._img_size.height()
        if w == 0 or h == 0:
            return

        if not self.prog or not self.prog.isLinked():
            print("Shader program not linked in paintGL")
            return

        # Lazy texture creation/update
        if self._texture is None or not self._texture.isCreated():
            self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
            self._texture.create()
            self._texture.setFormat(QOpenGLTexture.RGBA8_UNorm)  # Format of QImage
            self._texture.setMinificationFilter(QOpenGLTexture.Linear)
            self._texture.setMagnificationFilter(QOpenGLTexture.Linear)
            self._texture.setWrapMode(QOpenGLTexture.ClampToEdge)

        # Bind texture and upload data if dimensions changed or first time
        if self._texture.width() != w or self._texture.height() != h:
            self._texture.setSize(w, h, 1)  # width, height, depth
            self._texture.allocateStorage()  # Allocate based on format and size set

        # Upload the image data
        # The QImage.Format_RGBA8888 matches GL_RGBA and GL_UNSIGNED_BYTE pixel types
        self._texture.setData(
            self._pending_qimg, QOpenGLTexture.MipMapGeneration.NoMipmapGeneration
        )
        self._pending_qimg = None  # Consumed

        self.prog.bind()
        self.vao.bind()
        self._texture.bind(0)  # Bind texture to texture unit 0
        self.prog.setUniformValue("ourTexture", 0)  # Tell shader to use texture unit 0

        GL.glDrawElements(
            GL.GL_TRIANGLES, 6, GL.GL_UNSIGNED_INT, None
        )  # Draw using EBO

        self._texture.release(0)
        self.vao.release()
        self.prog.release()

    def resizeGL(self, w: int, h: int):
        GL.glViewport(0, 0, w, h)

    def minimumSizeHint(self):
        return QSize(50, 50)

    def sizeHint(self):
        if self._img_size.width() > 0:
            return self._img_size
        return QSize(640, 480)
