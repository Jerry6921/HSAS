import AppKit
import Foundation
import PDFKit
import Vision

func cgImage(from image: NSImage) -> CGImage? {
    var rect = NSRect(origin: .zero, size: image.size)
    return image.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

func recognize(_ image: CGImage) throws -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    if #available(macOS 13.0, *) {
        request.automaticallyDetectsLanguage = true
    }
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    let observations = (request.results ?? []).sorted {
        if abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.015 {
            return $0.boundingBox.midY > $1.boundingBox.midY
        }
        return $0.boundingBox.minX < $1.boundingBox.minX
    }
    return observations.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func recognizeImage(at url: URL) throws -> String {
    guard let image = NSImage(contentsOf: url), let value = cgImage(from: image) else {
        throw NSError(domain: "HIQSOCR", code: 2, userInfo: [NSLocalizedDescriptionKey: "Unreadable image"])
    }
    return try recognize(value)
}

func recognizePDF(at url: URL) throws -> String {
    guard let document = PDFDocument(url: url) else {
        throw NSError(domain: "HIQSOCR", code: 3, userInfo: [NSLocalizedDescriptionKey: "Unreadable PDF"])
    }
    var sections: [String] = []
    for index in 0..<document.pageCount {
        guard let page = document.page(at: index) else { continue }
        let bounds = page.bounds(for: .mediaBox)
        let scale = min(3.0, max(1.5, 2200.0 / max(bounds.width, bounds.height)))
        let thumbnail = page.thumbnail(
            of: NSSize(width: bounds.width * scale, height: bounds.height * scale),
            for: .mediaBox
        )
        guard let image = cgImage(from: thumbnail) else { continue }
        let text = try recognize(image)
        sections.append("--- Page \(index + 1) OCR ---\n\(text)")
    }
    return sections.joined(separator: "\n\n")
}

guard CommandLine.arguments.count >= 2 else {
    FileHandle.standardError.write(Data("usage: vision_ocr.swift FILE [FILE ...]\n".utf8))
    exit(2)
}

do {
    var sections: [String] = []
    for argument in CommandLine.arguments.dropFirst() {
        let url = URL(fileURLWithPath: argument)
        if url.pathExtension.lowercased() == "pdf" {
            sections.append(try recognizePDF(at: url))
            continue
        }
        let stem = url.deletingPathExtension().lastPathComponent
        let parts = stem.split(separator: "-")
        let label = parts.count >= 4 && parts[0] == "slide"
            ? "--- Slide \(parts[1]) OCR image \(parts[3]) ---"
            : "--- Image \(stem) OCR ---"
        sections.append("\(label)\n\(try recognizeImage(at: url))")
    }
    print(sections.joined(separator: "\n\n"))
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(1)
}
