import AppKit
let size = 1024.0
let img = NSImage(size: NSSize(width: size, height: size))
img.lockFocus()
let navy = NSColor(srgbRed: 0.106, green: 0.165, blue: 0.290, alpha: 1)
let inset = 100.0
let tile = NSRect(x: inset, y: inset, width: size - 2*inset, height: size - 2*inset)
let shadow = NSShadow(); shadow.shadowBlurRadius = 24; shadow.shadowOffset = NSSize(width: 0, height: -10); shadow.shadowColor = NSColor(white: 0, alpha: 0.3)
NSGraphicsContext.saveGraphicsState(); shadow.set()
navy.setFill(); NSBezierPath(roundedRect: tile, xRadius: 185, yRadius: 185).fill()
NSGraphicsContext.restoreGraphicsState()
// speech bubble
let bubble = NSBezierPath(roundedRect: NSRect(x: 245, y: 380, width: 534, height: 360), xRadius: 90, yRadius: 90)
let tail = NSBezierPath(); tail.move(to: NSPoint(x: 330, y: 400)); tail.line(to: NSPoint(x: 300, y: 285)); tail.line(to: NSPoint(x: 440, y: 390)); tail.close()
NSColor.white.setFill(); bubble.fill(); tail.fill()
// waveform bars inside the bubble
let heights = [70.0, 150.0, 220.0, 120.0, 180.0, 90.0]
let barW = 34.0, gap = 30.0
let total = Double(heights.count) * barW + Double(heights.count - 1) * gap
var x = 512 - total / 2
navy.setFill()
for h in heights { NSBezierPath(roundedRect: NSRect(x: x, y: 560 - h/2, width: barW, height: h), xRadius: barW/2, yRadius: barW/2).fill(); x += barW + gap }
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
