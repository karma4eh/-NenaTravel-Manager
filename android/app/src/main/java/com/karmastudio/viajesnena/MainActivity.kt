package com.karmastudio.viajesnena

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.*
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.floatingactionbutton.FloatingActionButton

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var layoutError: LinearLayout
    private lateinit var btnRetry: Button
    private lateinit var btnSettings: Button
    private lateinit var fabSettings: FloatingActionButton

    private var fileUploadCallback: ValueCallback<Array<Uri>>? = null

    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (fileUploadCallback != null) {
            val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            fileUploadCallback?.onReceiveValue(uris)
            fileUploadCallback = null
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Integracion de barras del sistema con la estetica nativa de la app
        configureSystemBars()

        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        swipeRefresh = findViewById(R.id.swipeRefresh)
        layoutError = findViewById(R.id.layoutError)
        btnRetry = findViewById(R.id.btnRetry)
        btnSettings = findViewById(R.id.btnSettings)
        fabSettings = findViewById(R.id.fabSettings)

        setupSwipeRefresh()
        setupWebView()
        setupListeners()
        setupBackNavigation()

        loadCurrentServer()
    }

    private fun configureSystemBars() {
        val darkBgColor = Color.parseColor("#0a1b2d")
        window.statusBarColor = darkBgColor
        window.navigationBarColor = darkBgColor

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.setSystemBarsAppearance(
                0,
                android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            )
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = 0
        }
    }

    private fun setupSwipeRefresh() {
        // Colores tematicos nativos de Viajes Nena
        swipeRefresh.setColorSchemeColors(
            Color.parseColor("#16b8b0"),
            Color.parseColor("#2563eb"),
            Color.parseColor("#38bdf8")
        )
        swipeRefresh.setProgressBackgroundColorSchemeColor(Color.parseColor("#0f172a"))
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        // Aceleracion por hardware para maxima fluidez a 60/120 FPS
        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null)
        webView.isVerticalScrollBarEnabled = false
        webView.isHorizontalScrollBarEnabled = false
        webView.overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS

        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        settings.setSupportZoom(false)
        settings.builtInZoomControls = false
        settings.displayZoomControls = false
        settings.allowFileAccess = true
        settings.allowContentAccess = true
        settings.cacheMode = WebSettings.LOAD_DEFAULT

        // Identificador de App Nativa para optimizaciones de servidor
        val defaultUa = settings.userAgentString
        settings.userAgentString = "$defaultUa ViajesNenaApp/1.0 (Android Native; KarmaStudio)"

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                layoutError.visibility = View.GONE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                swipeRefresh.isRefreshing = false
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                if (request?.isForMainFrame == true) {
                    swipeRefresh.isRefreshing = false
                    layoutError.visibility = View.VISIBLE
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                mWebView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                fileUploadCallback?.onReceiveValue(null)
                fileUploadCallback = filePathCallback

                val intent = fileChooserParams?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                    type = "*/*"
                    addCategory(Intent.CATEGORY_OPENABLE)
                }

                try {
                    filePickerLauncher.launch(intent)
                } catch (e: Exception) {
                    fileUploadCallback = null
                    Toast.makeText(this@MainActivity, "No se pudo abrir el selector de archivos", Toast.LENGTH_SHORT).show()
                    return false
                }
                return true
            }
        }
    }

    private fun setupListeners() {
        swipeRefresh.setOnRefreshListener {
            webView.reload()
        }

        btnRetry.setOnClickListener {
            layoutError.visibility = View.GONE
            swipeRefresh.isRefreshing = true
            webView.reload()
        }

        btnSettings.setOnClickListener {
            showServerConfigDialog()
        }

        fabSettings.setOnClickListener {
            showServerConfigDialog()
        }
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    finish()
                }
            }
        })
    }

    private fun loadCurrentServer() {
        val prefs = getSharedPreferences("viajes_nena_prefs", Context.MODE_PRIVATE)
        val defaultUrl = getString(R.string.default_server_url)
        val currentUrl = prefs.getString("server_url", defaultUrl) ?: defaultUrl
        webView.loadUrl(currentUrl)
    }

    private fun showServerConfigDialog() {
        val prefs = getSharedPreferences("viajes_nena_prefs", Context.MODE_PRIVATE)
        val currentUrl = prefs.getString("server_url", getString(R.string.default_server_url)) ?: ""

        val input = EditText(this).apply {
            setText(currentUrl)
            hint = "http://192.168.1.XX:8000/ o https://..."
            setSingleLine()
            setPadding(40, 30, 40, 30)
        }

        AlertDialog.Builder(this)
            .setTitle("⚙️ Configurar Servidor")
            .setMessage("Introduce la dirección IP local de tu PC o la URL de la nube de Viajes Nena:")
            .setView(input)
            .setPositiveButton("Guardar y Conectar") { _, _ ->
                var newUrl = input.text.toString().trim()
                if (newUrl.isNotEmpty()) {
                    if (!newUrl.startsWith("http://") && !newUrl.startsWith("https://")) {
                        newUrl = "http://$newUrl"
                    }
                    if (!newUrl.endsWith("/")) {
                        newUrl = "$newUrl/"
                    }
                    prefs.edit().putString("server_url", newUrl).apply()
                    Toast.makeText(this, "Conectando a: $newUrl", Toast.LENGTH_SHORT).show()
                    layoutError.visibility = View.GONE
                    swipeRefresh.isRefreshing = true
                    webView.loadUrl(newUrl)
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }
}
