from ij import IJ, ImagePlus
from ij.plugin.frame import RoiManager
from java.io import File

class OverlayLoader(ImagePlus.ImageListener):
    def imageOpened(self, imp):
        info = imp.getOriginalFileInfo()
        if info is None:
            return
        name = info.fileName
        if name is None:
            return
        base = name
        if base.lower().endswith('.tif'):
            base = base[:-4]
        zip_path = info.directory + base + '_overlays.zip'
        if File(zip_path).exists():
            rm = RoiManager.getInstance()
            if rm is None:
                rm = RoiManager()
            rm.runCommand('Open', zip_path)
            IJ.log('Loaded PRIM overlays: ' + zip_path)
    def imageClosed(self, imp):
        pass
    def imageUpdated(self, imp):
        pass

ImagePlus.addImageListener(OverlayLoader())
IJ.log('PRIM overlay loader enabled')
