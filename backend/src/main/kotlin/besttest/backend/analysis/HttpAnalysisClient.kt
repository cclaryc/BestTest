package besttest.backend.analysis

import java.net.http.HttpClient
import org.springframework.http.HttpStatusCode
import org.springframework.http.MediaType
import org.springframework.http.client.ClientHttpRequestFactory
import org.springframework.http.client.JdkClientHttpRequestFactory
import org.springframework.stereotype.Component
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClient
import tools.jackson.core.JacksonException
import tools.jackson.databind.ObjectMapper

@Component
class HttpAnalysisClient(
    builder: RestClient.Builder,
    private val objectMapper: ObjectMapper,
    properties: AnalysisProperties,
) : AnalysisClient {

    private val restClient: RestClient = builder
        .baseUrl(properties.baseUrl.toString())
        .requestFactory(requestFactory(properties))
        .build()

    override fun changedSymbols(request: ChangedSymbolsRequest, requestId: String?): AnalysisResult {
        // The body is turned into bytes here, not handed to Spring as an
        // object. Spring would stream an object with "Transfer-Encoding:
        // chunked", because it does not know the size in advance, and the
        // analysis service refuses chunked bodies (it needs Content-Length to
        // enforce its size limit before reading anything).
        val body = objectMapper.writeValueAsBytes(request)
        try {
            return restClient.post()
                .uri(CHANGED_SYMBOLS_PATH)
                .contentType(MediaType.APPLICATION_JSON)
                .contentLength(body.size.toLong())
                .accept(MediaType.APPLICATION_JSON, MediaType.APPLICATION_PROBLEM_JSON)
                .headers { headers ->
                    if (requestId != null) {
                        headers.set(REQUEST_ID_HEADER, requestId)
                    }
                }
                .body(body)
                .exchange { _, response -> interpret(response.statusCode, response.body.readAllBytes()) }
        } catch (error: ResourceAccessException) {
            // Spring wraps every I/O failure in this: refused connections,
            // timeouts, connections dropped halfway.
            throw AnalysisUnavailableException("analysis service could not be reached: ${error.message}", error)
        }
    }

    private fun interpret(status: HttpStatusCode, bytes: ByteArray): AnalysisResult {
        if (status.is2xxSuccessful) {
            val response = try {
                objectMapper.readValue(bytes, ChangedSymbolsResponse::class.java)
            } catch (error: JacksonException) {
                throw AnalysisUnavailableException("analysis service sent a response that does not match the contract", error)
            }
            return AnalysisResult(response, String(bytes, Charsets.UTF_8))
        }

        val problem = try {
            objectMapper.readValue(bytes, AnalysisProblem::class.java)
        } catch (error: JacksonException) {
            null
        }
        if (status.is4xxClientError) {
            throw AnalysisRejectedException(
                code = problem?.code ?: "rejected",
                detail = problem?.detail ?: problem?.title,
            )
        }
        throw AnalysisUnavailableException(
            "analysis service failed with status ${status.value()}" +
                (problem?.requestId?.let { " (its request id: $it)" } ?: ""),
        )
    }

    companion object {
        const val CHANGED_SYMBOLS_PATH = "/v1/changed-symbols"
        const val REQUEST_ID_HEADER = "X-Request-ID"

        private fun requestFactory(properties: AnalysisProperties): ClientHttpRequestFactory {
            val httpClient = HttpClient.newBuilder()
                // Plain HTTP/1.1. Left to itself the JDK client first tries to
                // upgrade a cleartext connection to HTTP/2, which gains nothing here.
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(properties.connectTimeout)
                .build()
            val factory = JdkClientHttpRequestFactory(httpClient)
            // Without a read timeout a stuck analysis would hold a request
            // thread forever. Every call across the network needs a deadline.
            factory.setReadTimeout(properties.readTimeout)
            return factory
        }
    }
}
