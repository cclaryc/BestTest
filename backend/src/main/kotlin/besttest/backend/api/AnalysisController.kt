package besttest.backend.api

import besttest.backend.jobs.AnalysisRunService
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.validation.Valid
import java.net.URI
import java.util.UUID
import org.slf4j.MDC
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

/**
 * A controller translates between HTTP and the application: it reads the
 * request, calls one service method, and shapes the answer. It holds no logic
 * of its own, which is why it needs no unit test beyond the integration test.
 */
@RestController
@RequestMapping("/api/analyses")
class AnalysisController(
    private val service: AnalysisRunService,
    private val objectMapper: ObjectMapper,
) {
    @PostMapping
    fun start(@Valid @RequestBody body: StartAnalysisRequest): ResponseEntity<AnalysisRunView> {
        val run = service.start(
            base = body.base.toRevision(),
            head = body.head.toRevision(),
            diff = body.diff,
            requestId = MDC.get(RequestIdFilter.MDC_KEY),
        )
        // 201 even when the run failed: a run was created, and its status says
        // how it ended. Once analyses run in the background this endpoint will
        // answer before the outcome is known, and clients already read `status`.
        return ResponseEntity
            .created(URI.create("/api/analyses/${run.id}"))
            .body(AnalysisRunView.of(run, objectMapper, includeResult = true))
    }

    @GetMapping("/{id}")
    fun get(@PathVariable id: UUID): AnalysisRunView =
        AnalysisRunView.of(service.get(id), objectMapper, includeResult = true)

    @GetMapping
    fun latest(): List<AnalysisRunView> =
        service.latest().map { AnalysisRunView.of(it, objectMapper, includeResult = false) }
}
