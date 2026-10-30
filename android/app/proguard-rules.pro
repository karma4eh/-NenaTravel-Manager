# Reglas basicas de Proguard para Viajes Nena
-keepattributes *Annotation*
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
