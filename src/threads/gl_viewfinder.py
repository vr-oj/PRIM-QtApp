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
import ctypes


class GLViewfinder(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._texture = None
        self._img_size = QSize(0, 0)
        self._pending_qimg = None
        self.prog = None
        self.vao = QOpenGLVertexArrayObject()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.ebo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self._gl_initialized_successfully = False  # Add this flag

    def initializeGL(self):
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)

        self.prog = QOpenGLShaderProgram(self)

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
            return  # Exit if error
        if not self.prog.addShaderFromSourceCode(QOpenGLShader.Fragment, fs_source):
            print(f"Fragment shader compilation error: {self.prog.log()}")
            return  # Exit if error
        if not self.prog.link():
            print(f"Shader linking error: {self.prog.log()}")
            return  # Exit if error

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
        # It's good practice to check if allocate succeeds, though it doesn't return a bool
        try:
            self.vbo.allocate(vertex_qbytearray, vertex_qbytearray.size())
        except Exception as e:
            print(f"Error allocating VBO: {e}")
            self.vao.release()  # Release VAO before returning on error
            return  # Exit if error

        if not self.ebo.isCreated():
            self.ebo.create()
        self.ebo.bind()
        try:
            self.ebo.allocate(index_qbytearray, index_qbytearray.size())
        except Exception as e:
            print(f"Error allocating EBO: {e}")
            self.vbo.release()  # Release VBO
            self.vao.release()  # Release VAO
            return  # Exit if error

        float_size = ctypes.sizeof(ctypes.c_float)
        stride = 5 * float_size

        self.prog.enableAttributeArray(0)
        self.prog.setAttributeBuffer(0, GL.GL_FLOAT, 0, 3, stride)

        self.prog.enableAttributeArray(1)
        self.prog.setAttributeBuffer(1, GL.GL_FLOAT, 3 * float_size, 2, stride)

        self.vao.release()
        self.vbo.release()
        self.ebo.release()
        # self.prog.release() # Program should remain bound if VAO attributes point to it.
        # Or, rebind in paintGL explicitly. Binding in paintGL is safer.

        self._gl_initialized_successfully = True  # Set flag on successful completion
        print("GLViewfinder: initializeGL completed successfully.")

    def update_frame(self, qimg: QImage):
        if qimg.isNull():
            # If camera disconnects, we might get null images.
            # In this case, we could clear the pending image or set a placeholder.
            # For now, just don't update if null.
            # self._pending_qimg = None # Optionally clear
            # self.update() # Trigger a repaint to potentially clear the view
            return

        self._pending_qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
        self._img_size = self._pending_qimg.size()
        self.update()

    def paintGL(self):
        if not self._gl_initialized_successfully:  # New guard
            # Optionally clear to a color if not initialized
            GL.glClearColor(0.1, 0.1, 0.1, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            return

        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)  # Default clear

        if self._pending_qimg is None or self._pending_qimg.isNull():
            # No new image to upload to texture, but GL might be initialized.
            # We could draw a blank screen or last valid texture if we stored it differently.
            # For now, just return to avoid errors with texture operations.
            return

        w, h = self._img_size.width(), self._img_size.height()
        if w == 0 or h == 0:
            return

        if not self.prog or not self.prog.isLinked():
            print("Shader program not linked in paintGL")
            return

        # Ensure VAO is valid (though it should be if _gl_initialized_successfully is true)
        if not self.vao.isCreated():
            print("VAO not created in paintGL")
            return

        if self._texture is None or not self._texture.isCreated():
            self._texture = QOpenGLTexture(QOpenGLTexture.Target2D)
            self._texture.create()
            self._texture.setFormat(QOpenGLTexture.RGBA8_UNorm)
            self._texture.setMinificationFilter(QOpenGLTexture.Linear)
            self._texture.setMagnificationFilter(QOpenGLTexture.Linear)
            self._texture.setWrapMode(QOpenGLTexture.ClampToEdge)

        if self._texture.width() != w or self._texture.height() != h:
            self._texture.setSize(w, h, 1)
            self._texture.allocateStorage()

        self._texture.setData(self._pending_qimg, QOpenGLTexture.DontGenerateMipMaps)
        self._pending_qimg = None

        self.prog.bind()
        self.vao.bind()  # This binds the VBO and EBO that were configured with this VAO

        self._texture.bind(0)
        self.prog.setUniformValue("ourTexture", 0)

        GL.glDrawElements(GL.GL_TRIANGLES, 6, GL.GL_UNSIGNED_INT, None)

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
