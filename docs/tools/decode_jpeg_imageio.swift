import AppKit
import CoreGraphics
import ImageIO
import Foundation

func fail(_ message: String) -> Never {
    fputs("\(message)\n", stderr)
    exit(2)
}
guard CommandLine.arguments.count == 3 else {
    fail("Usage: decode_jpeg_imageio INPUT.jpg OUTPUT.rgba")
}
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
guard let source = CGImageSourceCreateWithURL(input as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fail("ImageIO could not create an image")
}
let width = image.width, height = image.height
guard width == 1920 && height == 1080 else { fail("Unexpected image dimensions") }
let rowBytes = width * 4
var rgba = [UInt8](repeating: 0, count: rowBytes * height)
guard let space = CGColorSpace(name: CGColorSpace.sRGB),
      let context = CGContext(data: &rgba, width: width, height: height,
                              bitsPerComponent: 8, bytesPerRow: rowBytes,
                              space: space,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue |
                                          CGBitmapInfo.byteOrder32Big.rawValue) else {
    fail("Could not create sRGB CGContext")
}
context.interpolationQuality = .none
context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
let data = Data(rgba)
do { try data.write(to: output, options: .atomic) }
catch { fail("Could not write output: \(error)") }
let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] ?? [:]
let colorModel = properties[kCGImagePropertyColorModel] ?? "unknown"
print("width=\(width) height=\(height) image_color_space=\(image.colorSpace?.name as String? ?? "unknown") color_model=\(colorModel) output=sRGB RGBA")
