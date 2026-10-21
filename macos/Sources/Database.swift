import Foundation

struct AssetRow: Identifiable, Hashable {
    let id: String
    let name: String
    let project: String
    let atype: String
    let state: String
    let inbox: Bool
    let latestSeq: Int
}

struct VersionRow: Identifiable {
    let id: String
    let seq: Int
    let hash: String
    let author: String
    let tool: String
    let model: String
    let intent: String
    var shortHash: String { String(hash.prefix(12)) }
}

struct NodeRow: Identifiable {
    let name: String
    let kind: String
    let path: String
    let files: Int
    let bytes: Int
    var id: String { name }
}

struct CollectionFile: Identifiable {
    let id: String
    let name: String
    let project: String
    let atype: String
    let state: String
    let size: Int
    let thumb: String
    let excerpt: String
    let displayTitle: String
    var title: String { displayTitle.isEmpty ? name : displayTitle }
}

struct BreakdownRow: Identifiable {
    let label: String
    let files: Int
    let bytes: Int
    var id: String { label }
}

struct DayRow: Identifiable {
    let day: String
    let files: Int
    let bytes: Int
    var id: String { day }
}

struct DashboardData {
    var totalFiles = 0
    var totalCopies = 0
    var totalBytes = 0
    var conversations = 0
    var finals = 0
    var reclaimable = 0
    var protectTotal = 0
    var protectAtRisk = 0
    var byCategory: [BreakdownRow] = []
    var byType: [BreakdownRow] = []
    var byDay: [DayRow] = []
}

struct ConversationRow: Identifiable {
    let id: String
    let title: String
    let tool: String
    let inferred: Bool
    let files: Int
    let bytes: Int
}

struct DupRow: Identifiable {
    let hash: String
    let copies: Int
    let sizeEach: Int
    let wasted: Int
    let example: String
    var id: String { hash }
}

final class Database {
    private var db: OpaquePointer?
    let path: String

    init(path: String) {
        self.path = path
        sqlite3_open(path, &db)
    }

    private func query(_ sql: String, binds: [String] = []) -> [[String]] {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }
        for (i, v) in binds.enumerated() {
            sqlite3_bind_text(stmt, Int32(i + 1), v, -1,
                              unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        }
        var rows: [[String]] = []
        let ncols = sqlite3_column_count(stmt)
        while sqlite3_step(stmt) == SQLITE_ROW {
            var row: [String] = []
            for c in 0..<ncols {
                if let txt = sqlite3_column_text(stmt, c) {
                    row.append(String(cString: txt))
                } else {
                    row.append("")
                }
            }
            rows.append(row)
        }
        return rows
    }

    @discardableResult
    private func execute(_ sql: String, binds: [String] = []) -> Bool {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return false }
        defer { sqlite3_finalize(stmt) }
        for (i, v) in binds.enumerated() {
            sqlite3_bind_text(stmt, Int32(i + 1), v, -1,
                              unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        }
        return sqlite3_step(stmt) == SQLITE_DONE
    }

    private var latestExpr: String {
        "COALESCE((SELECT MAX(l.mtime) FROM locations l " +
        "JOIN versions v ON v.blob_hash=l.hash WHERE v.asset_id=a.id), a.created)"
    }

    func assets(section: String, search: String, sort: String = "created") -> [AssetRow] {
        var whereClause = "1=1"
        if section == "inbox" { whereClause = "a.in_inbox=1" }
        if section == "finals" { whereClause = "a.state IN ('final','published')" }
        var binds: [String] = []
        if !search.isEmpty {
            whereClause += " AND (a.name LIKE ? OR a.project LIKE ?)"
            binds = ["%" + search + "%", "%" + search + "%"]
        }
        let order: String
        switch sort {
        case "latest": order = "\(latestExpr) DESC"
        case "size": order = "\(sizeExpr) DESC"
        case "name": order = "a.name ASC"
        default: order = "a.created DESC"
        }
        let sql = """
            SELECT a.id, a.name, a.project, a.atype, a.state, a.in_inbox,
                   COALESCE((SELECT MAX(seq) FROM versions v WHERE v.asset_id=a.id),1)
            FROM assets a WHERE \(whereClause) ORDER BY \(order) LIMIT 500
            """
        return query(sql, binds: binds).map {
            AssetRow(id: $0[0], name: $0[1], project: $0[2], atype: $0[3],
                     state: $0[4], inbox: $0[5] == "1", latestSeq: Int($0[6]) ?? 1)
        }
    }

    func versions(assetId: String) -> [VersionRow] {
        let sql = """
            SELECT v.id, v.seq, v.blob_hash, v.author,
                   COALESCE(p.tool,''), COALESCE(p.model,''), COALESCE(p.intent,'')
            FROM versions v LEFT JOIN provenance p ON p.version_id=v.id
            WHERE v.asset_id=? ORDER BY v.seq DESC
            """
        return query(sql, binds: [assetId]).map {
            VersionRow(id: $0[0], seq: Int($0[1]) ?? 0, hash: $0[2], author: $0[3],
                       tool: $0[4], model: $0[5], intent: $0[6])
        }
    }

    func locations(assetId: String) -> [(node: String, path: String)] {
        let sql = """
            SELECT l.node, l.path FROM locations l
            WHERE l.hash = (SELECT blob_hash FROM versions WHERE asset_id=?
                            ORDER BY seq DESC LIMIT 1)
            """
        return query(sql, binds: [assetId]).map { (node: $0[0], path: $0[1]) }
    }

    func nodes() -> [NodeRow] {
        let sql = """
            SELECT n.name, n.kind, n.path,
                   (SELECT COUNT(*) FROM locations l WHERE l.node=n.name),
                   (SELECT COALESCE(SUM(size),0) FROM locations l WHERE l.node=n.name)
            FROM nodes n ORDER BY n.name
            """
        return query(sql).map {
            NodeRow(name: $0[0], kind: $0[1], path: $0[2],
                    files: Int($0[3]) ?? 0, bytes: Int($0[4]) ?? 0)
        }
    }

    func dupGroups() -> [DupRow] {
        let sql = """
            SELECT b.hash, COUNT(l.path), b.size,
                   (SELECT path FROM blob_locations bl WHERE bl.hash=b.hash LIMIT 1)
            FROM blobs b JOIN blob_locations l ON l.hash=b.hash
            GROUP BY b.hash HAVING COUNT(l.path)>1
            ORDER BY b.size*(COUNT(l.path)-1) DESC LIMIT 200
            """
        return query(sql).map {
            let copies = Int($0[1]) ?? 0
            let size = Int($0[2]) ?? 0
            return DupRow(hash: $0[0], copies: copies, sizeEach: size,
                          wasted: size * (copies - 1),
                          example: ($0[3] as NSString).lastPathComponent)
        }
    }

    func preview(assetId: String) -> (thumb: String, excerpt: String, title: String) {
        let sql = """
            SELECT COALESCE(p.thumb_path,''), COALESCE(p.excerpt,''),
                   COALESCE(p.display_title,'')
            FROM versions v LEFT JOIN previews p ON p.hash=v.blob_hash
            WHERE v.asset_id=? ORDER BY v.seq DESC LIMIT 1
            """
        guard let r = query(sql, binds: [assetId]).first else { return ("", "", "") }
        return (r[0], r[1], r[2])
    }

    func conversation(assetId: String)
        -> (tool: String, model: String, title: String, inferred: Bool, prompt: String)
    {
        let sql = """
            SELECT COALESCE(p.tool,''), COALESCE(p.model,''),
                   COALESCE(c.title,''), COALESCE(c.inferred,0),
                   COALESCE(p.prompt,'')
            FROM versions v
            LEFT JOIN provenance p ON p.version_id=v.id
            LEFT JOIN conversations c ON c.id=p.conversation_id
            WHERE v.asset_id=? ORDER BY v.seq DESC LIMIT 1
            """
        guard let r = query(sql, binds: [assetId]).first else {
            return ("", "", "", false, "")
        }
        return (r[0], r[1], r[2], r[3] == "1", r[4])
    }

    func conversations() -> [ConversationRow] {
        let sql = """
            SELECT c.id, c.title, c.tool, c.inferred,
                   COUNT(DISTINCT v.asset_id),
                   (SELECT COALESCE(SUM(size),0) FROM blobs WHERE hash IN
                     (SELECT DISTINCT vv.blob_hash FROM versions vv
                      JOIN provenance pp ON pp.version_id=vv.id
                      WHERE pp.conversation_id=c.id))
            FROM conversations c
            LEFT JOIN provenance p ON p.conversation_id=c.id
            LEFT JOIN versions v ON v.id=p.version_id
            GROUP BY c.id ORDER BY 5 DESC
            """
        return query(sql).map {
            ConversationRow(id: $0[0], title: $0[1], tool: $0[2],
                            inferred: $0[3] == "1",
                            files: Int($0[4]) ?? 0, bytes: Int($0[5]) ?? 0)
        }
    }

    func conversationFiles(_ cid: String) -> [AssetRow] {
        let sql = """
            SELECT DISTINCT a.id, a.name, a.project, a.atype, a.state, a.in_inbox,
                   COALESCE((SELECT MAX(seq) FROM versions v WHERE v.asset_id=a.id),1)
            FROM assets a
            JOIN versions v ON v.asset_id=a.id
            JOIN provenance p ON p.version_id=v.id
            WHERE p.conversation_id=? ORDER BY a.atype, a.name LIMIT 500
            """
        return query(sql, binds: [cid]).map {
            AssetRow(id: $0[0], name: $0[1], project: $0[2], atype: $0[3],
                     state: $0[4], inbox: $0[5] == "1", latestSeq: Int($0[6]) ?? 1)
        }
    }

    private var timeExpr: String {
        "COALESCE((SELECT MIN(l.mtime) FROM locations l " +
        "JOIN versions v ON v.blob_hash=l.hash WHERE v.asset_id=a.id), a.created)"
    }

    private var sizeExpr: String {
        "COALESCE((SELECT size FROM blobs WHERE hash=" +
        "(SELECT blob_hash FROM versions WHERE asset_id=a.id " +
        "ORDER BY seq DESC LIMIT 1)),0)"
    }

    func dashboard() -> DashboardData {
        var d = DashboardData()
        let one = { (sql: String) -> Int in
            Int(self.query(sql).first?.first ?? "0") ?? 0
        }
        d.totalFiles = one("SELECT COUNT(*) FROM assets")
        d.totalCopies = one("SELECT COUNT(*) FROM locations")
        d.totalBytes = one(
            "SELECT COALESCE(SUM(b.size),0) FROM locations l " +
            "JOIN blobs b ON b.hash=l.hash"
        )
        d.conversations = one("SELECT COUNT(*) FROM conversations")
        d.finals = one("SELECT COUNT(*) FROM assets WHERE state IN ('final','published')")
        d.reclaimable = one(
            "SELECT COALESCE(SUM(w),0) FROM (SELECT b.size*(COUNT(l.path)-1) AS w " +
            "FROM blobs b JOIN blob_locations l ON l.hash=b.hash " +
            "GROUP BY b.hash HAVING COUNT(l.path)>1)"
        )
        d.protectTotal = one("SELECT COUNT(*) FROM assets WHERE importance='protect'")
        d.protectAtRisk = one(
            "SELECT COUNT(*) FROM assets a WHERE a.importance='protect' AND " +
            "(SELECT COUNT(DISTINCT node) FROM locations l WHERE l.hash=" +
            "(SELECT blob_hash FROM versions WHERE asset_id=a.id " +
            "ORDER BY seq DESC LIMIT 1)) < 2"
        )
        d.byCategory = query(
            "SELECT COALESCE(NULLIF(a.category,''),'未分类'), COUNT(*), " +
            "SUM(\(sizeExpr)) FROM assets a GROUP BY 1 ORDER BY 2 DESC"
        ).map { BreakdownRow(label: $0[0], files: Int($0[1]) ?? 0, bytes: Int($0[2]) ?? 0) }
        d.byType = query(
            "SELECT a.atype, COUNT(*), SUM(\(sizeExpr)) FROM assets a " +
            "GROUP BY 1 ORDER BY 2 DESC"
        ).map { BreakdownRow(label: $0[0], files: Int($0[1]) ?? 0, bytes: Int($0[2]) ?? 0) }
        d.byDay = query(
            "SELECT date(\(timeExpr),'unixepoch','localtime'), COUNT(*), " +
            "SUM(\(sizeExpr)) FROM assets a GROUP BY 1 ORDER BY 1 DESC LIMIT 90"
        ).map { DayRow(day: $0[0], files: Int($0[1]) ?? 0, bytes: Int($0[2]) ?? 0) }
        return d
    }

    func filesByTime(from: Double?, to: Double?) -> [AssetRow] {
        var cond = "1=1"
        var binds: [String] = []
        if let from { cond += " AND \(timeExpr) >= ?"; binds.append(String(from)) }
        if let to { cond += " AND \(timeExpr) < ?"; binds.append(String(to)) }
        let sql = """
            SELECT a.id, a.name, a.project, a.atype, a.state, a.in_inbox,
                   COALESCE((SELECT MAX(seq) FROM versions v WHERE v.asset_id=a.id),1)
            FROM assets a WHERE \(cond) ORDER BY \(timeExpr) DESC LIMIT 500
            """
        return query(sql, binds: binds).map {
            AssetRow(id: $0[0], name: $0[1], project: $0[2], atype: $0[3],
                     state: $0[4], inbox: $0[5] == "1", latestSeq: Int($0[6]) ?? 1)
        }
    }

    func filesFiltered(category: String?, type: String?, protectOnly: Bool,
                       finalsOnly: Bool, from: Double?, to: Double?)
        -> (rows: [AssetRow], total: Int)
    {
        var cond = "1=1"
        var binds: [String] = []
        if let category { cond += " AND COALESCE(a.category,'')=?"; binds.append(category) }
        if let type { cond += " AND a.atype=?"; binds.append(type) }
        if protectOnly { cond += " AND a.importance='protect'" }
        if finalsOnly { cond += " AND a.state IN ('final','published')" }
        if let from { cond += " AND \(timeExpr) >= ?"; binds.append(String(from)) }
        if let to { cond += " AND \(timeExpr) < ?"; binds.append(String(to)) }
        let total = Int(query("SELECT COUNT(*) FROM assets a WHERE \(cond)", binds: binds).first?.first ?? "0") ?? 0
        let sql = """
            SELECT a.id, a.name, a.project, a.atype, a.state, a.in_inbox,
                   COALESCE((SELECT MAX(seq) FROM versions v WHERE v.asset_id=a.id),1)
            FROM assets a WHERE \(cond) ORDER BY \(timeExpr) DESC LIMIT 500
            """
        let rows = query(sql, binds: binds).map {
            AssetRow(id: $0[0], name: $0[1], project: $0[2], atype: $0[3],
                     state: $0[4], inbox: $0[5] == "1", latestSeq: Int($0[6]) ?? 1)
        }
        return (rows, total)
    }

    func filesForDrill(category: String?, type: String?, protectOnly: Bool,
                       finalsOnly: Bool) -> [CollectionFile]
    {
        var cond = "1=1"
        var binds: [String] = []
        if let category { cond += " AND COALESCE(a.category,'')=?"; binds.append(category) }
        if let type { cond += " AND a.atype=?"; binds.append(type) }
        if protectOnly { cond += " AND a.importance='protect'" }
        if finalsOnly { cond += " AND a.state IN ('final','published')" }
        let sql = """
            SELECT a.id, a.name, a.project, a.atype, a.state,
                   COALESCE((SELECT size FROM blobs WHERE hash=
                     (SELECT blob_hash FROM versions WHERE asset_id=a.id
                      ORDER BY seq DESC LIMIT 1)),0),
                   COALESCE(pv.thumb_path,''), COALESCE(pv.excerpt,''),
                   COALESCE(pv.display_title,'')
            FROM assets a
            LEFT JOIN previews pv ON pv.hash =
              (SELECT blob_hash FROM versions WHERE asset_id=a.id
               ORDER BY seq DESC LIMIT 1)
            WHERE \(cond) ORDER BY a.name LIMIT 2000
            """
        return query(sql, binds: binds).map {
            CollectionFile(
                id: $0[0], name: $0[1], project: $0[2], atype: $0[3],
                state: $0[4], size: Int($0[5]) ?? 0, thumb: $0[6],
                excerpt: $0[7], displayTitle: $0[8]
            )
        }
    }

    func settings() -> [String: String] {
        var out: [String: String] = [:]
        for r in query("SELECT key, value FROM settings") {
            out[r[0]] = r[1]
        }
        return out
    }

    func setSetting(_ key: String, _ value: String) {
        execute("INSERT OR REPLACE INTO settings VALUES (?,?)", binds: [key, value])
    }

    func cleanupPreview(staleDays: Int) -> (stale: Int, dedup: Int, ephemeral: Int) {
        let one = { (sql: String) -> Int in
            Int(self.query(sql).first?.first ?? "0") ?? 0
        }
        let cutoff = Date().timeIntervalSince1970 - Double(staleDays) * 86400
        return (
            one("SELECT COUNT(*) FROM versions v WHERE v.seq < " +
                "(SELECT MAX(seq) FROM versions WHERE asset_id=v.asset_id) " +
                "AND v.created < \(cutoff)"),
            one("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) AS c " +
                "FROM blob_locations GROUP BY hash HAVING c>1)"),
            one("SELECT COUNT(*) FROM assets WHERE importance='ephemeral'")
        )
    }

    func promote(assetId: String) {
        execute("UPDATE assets SET state='final', in_inbox=0 WHERE id=?", binds: [assetId])
    }

    func counts() -> (inbox: Int, total: Int, finals: Int, dups: Int, convs: Int) {
        let one = { (sql: String) -> Int in
            Int(self.query(sql).first?.first ?? "0") ?? 0
        }
        return (
            one("SELECT COUNT(*) FROM assets WHERE in_inbox=1"),
            one("SELECT COUNT(*) FROM assets"),
            one("SELECT COUNT(*) FROM assets WHERE state IN ('final','published')"),
            one("SELECT COUNT(*) FROM (SELECT b.hash FROM blobs b JOIN blob_locations l ON l.hash=b.hash GROUP BY b.hash HAVING COUNT(l.path)>1)"),
            one("SELECT COUNT(*) FROM conversations")
        )
    }
}

func humanBytes(_ n: Int) -> String {
    let f = ByteCountFormatter()
    f.countStyle = .file
    return f.string(fromByteCount: Int64(n))
}
