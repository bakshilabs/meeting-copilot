// systap: captures computer audio (every app: Teams, Meet, Zoom...) and the
// default microphone via ScreenCaptureKit, and writes 16 kHz mono int16 PCM
// to stdout as framed packets: [1 byte source: 0=mic 1=system][u32 LE byte length][samples].
import Foundation
import ScreenCaptureKit
import CoreMedia
import AVFoundation

let targetRate = 16000.0
let outLock = NSLock()

func emit(_ tag: UInt8, _ samples: [Int16]) {
    if samples.isEmpty { return }
    var data = Data([tag])
    var n = UInt32(samples.count * 2).littleEndian
    withUnsafeBytes(of: &n) { data.append(contentsOf: $0) }
    samples.withUnsafeBufferPointer { data.append(Data(buffer: $0)) }
    outLock.lock()
    FileHandle.standardOutput.write(data)
    outLock.unlock()
}

// Mono float samples from any PCM sample buffer (float32 or int16, interleaved or not).
func monoFloats(_ sb: CMSampleBuffer) -> ([Float], Double)? {
    guard let desc = sb.formatDescription?.audioStreamBasicDescription else { return nil }
    let channels = Int(desc.mChannelsPerFrame)
    let isFloat = desc.mFormatFlags & kAudioFormatFlagIsFloat != 0
    let nonInterleaved = desc.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
    let frames = CMSampleBufferGetNumSamples(sb)
    if frames == 0 || channels == 0 { return nil }
    var out = [Float](repeating: 0, count: frames)
    do {
        try sb.withAudioBufferList { abl, _ in
            let bufs = Array(abl)
            for (bi, buf) in bufs.enumerated() {
                guard let p = buf.mData else { continue }
                let chInBuf = nonInterleaved ? 1 : channels
                for f in 0..<frames {
                    var acc: Float = 0
                    for c in 0..<chInBuf {
                        let idx = f * chInBuf + c
                        if isFloat { acc += p.assumingMemoryBound(to: Float.self)[idx] }
                        else { acc += Float(p.assumingMemoryBound(to: Int16.self)[idx]) / 32768 }
                    }
                    out[f] += acc
                }
                _ = bi
            }
        }
    } catch { return nil }
    let scale = 1 / Float(channels)
    for i in 0..<frames { out[i] *= scale }
    return (out, desc.mSampleRate)
}

// Box-filtered resample to 16 kHz.
func resample(_ x: [Float], from rate: Double) -> [Int16] {
    let ratio = rate / targetRate
    let n = Int(Double(x.count) / ratio)
    var y = [Int16](repeating: 0, count: n)
    let half = max(ratio / 2, 0.5)
    for i in 0..<n {
        let centre = Double(i) * ratio
        let a = max(0, Int(centre - half + 0.5)), b = min(x.count - 1, Int(centre + half - 0.5))
        var s: Float = 0
        if b >= a { for j in a...b { s += x[j] }; s /= Float(b - a + 1) }
        y[i] = Int16(max(-1, min(1, s)) * 32767)
    }
    return y
}

final class Tap: NSObject, SCStreamOutput, SCStreamDelegate {
    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        let tag: UInt8
        switch type {
        case .audio: tag = 1
        case .microphone: tag = 0
        default: return
        }
        guard sb.isValid, let (x, rate) = monoFloats(sb) else { return }
        emit(tag, resample(x, from: rate))
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write("systap stopped: \(error.localizedDescription)\n".data(using: .utf8)!)
        exit(1)
    }
}

let tap = Tap()
var keep: SCStream?
let useMic = !CommandLine.arguments.contains("--no-mic")

Task {
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else { throw NSError(domain: "systap", code: 1, userInfo: [NSLocalizedDescriptionKey: "no display"]) }
        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.sampleRate = Int(targetRate)
        cfg.channelCount = 1
        cfg.excludesCurrentProcessAudio = true
        cfg.captureMicrophone = useMic
        cfg.width = 2
        cfg.height = 2
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let stream = SCStream(filter: filter, configuration: cfg, delegate: tap)
        let q = DispatchQueue(label: "systap.audio")
        try stream.addStreamOutput(tap, type: .screen, sampleHandlerQueue: DispatchQueue(label: "systap.screen"))
        try stream.addStreamOutput(tap, type: .audio, sampleHandlerQueue: q)
        if useMic { try stream.addStreamOutput(tap, type: .microphone, sampleHandlerQueue: q) }
        try await stream.startCapture()
        keep = stream
        FileHandle.standardError.write("systap: capturing (mic: \(useMic))\n".data(using: .utf8)!)
    } catch {
        FileHandle.standardError.write("systap failed: \(error.localizedDescription)\n".data(using: .utf8)!)
        exit(1)
    }
}
signal(SIGPIPE, SIG_IGN)
dispatchMain()
