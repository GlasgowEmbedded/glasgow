<!--
  @package
  Generates a BOM list suitable for import into Mouser BOM tool.

  The command line is
    xsltproc -o "%O_bom.txt" "%P/bom2mouser.xslt" "%I"
-->

<!--
  nodes are grouped using the Muenchian method;
  see http://www.jenitennison.com/xslt/grouping/muenchian.html
-->

<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
  <xsl:output method="text"/>

  <xsl:key name="mfgPartNumber" match="comp" use="fields/field[@name='MPN']" />

  <xsl:template match="/export">
    <xsl:apply-templates select="components"/>
  </xsl:template>

  <xsl:template match="components">
    <xsl:for-each select="comp[count(. | key('mfgPartNumber', fields/field[@name='MPN'])[1]) = 1]">

      <xsl:sort select="fields/field[@name='MPN']"/>

      <xsl:if test="count(key('mfgPartNumber', fields/field[@name='MPN'])) > 0">

        <xsl:value-of select="fields/field[@name='MPN']"/>
        <xsl:text>|</xsl:text>

        <xsl:value-of select="count(key('mfgPartNumber', fields/field[@name='MPN']))"/>
        <xsl:text>|</xsl:text>

        <xsl:for-each select="key('mfgPartNumber', fields/field[@name='MPN'])">

          <xsl:sort select="@ref" />
          <xsl:value-of select="@ref"/>
          <xsl:text> </xsl:text>

        </xsl:for-each>
        <xsl:text>&#xa;</xsl:text>

      </xsl:if>

    </xsl:for-each>
  </xsl:template>

</xsl:stylesheet>
