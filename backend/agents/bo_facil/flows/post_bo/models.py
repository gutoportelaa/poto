from pydantic import BaseModel, Field

# ===============================
# API PAYLOAD MODELS
# ===============================


class Address(BaseModel):
    """Address information for API payload."""

    cep: str | None = Field(None, description="CEP (postal code)")
    rua: str | None = Field(None, description="Street name")
    numero: str | None = Field(None, description="Street number")
    bairro: str | None = Field(None, description="Neighborhood")
    cidade: str | None = Field(None, description="City")
    estado: str | None = Field(None, description="State abbreviation (2 chars)")
    geo_lat: float | None = Field(None, description="Latitude")
    geo_long: float | None = Field(None, description="Longitude")
    ponto_referencia: str | None = Field(None, description="Reference point")


class Person(BaseModel):
    """Person information for API payload."""

    cpf: str = Field(..., description="CPF number")
    nome_completo: str | None = Field(None, description="Full name")
    nome_completo_mae: str | None = Field(None, description="Mother's full name")
    telefone_contato: str | None = Field(None, description="Contact phone")
    email_contato: str | None = Field(None, description="Contact email")
    naturalidade: str | None = Field(None, description="Birth city/nationality")
    nacionalidade: str | None = Field(None, description="Nationality")
    data_nascimento: str | None = Field(None, description="Birth date (YYYY-MM-DD)")
    profissao: str | None = Field(None, description="Profession")
    sexo: str | None = Field(None, description="Gender")
    estado_civil: str | None = Field(None, description="Marital status")
    endereco: Address | None = Field(None, description="Address information")


class IncidentObject(BaseModel):
    """Object involved in the incident."""

    tipo_objeto: str = Field(..., description="Object type (celular, veiculo, documento)")
    descricao: str = Field(..., description="Object description")
    modelo: str | None = Field(None, description="Model")
    marca: str | None = Field(None, description="Brand")
    cor: str | None = Field(None, description="Color")
    # celular-specific
    sistema_operacional: str | None = Field(None, description="OS (Android, Ios)")
    quantidade_cameras: int | None = Field(None, description="Number of cameras")
    suporte_nfc: bool | None = Field(None, description="NFC support")
    preco_estimado: float | None = Field(None, description="Estimated price")
    numero_serie: str | None = Field(None, description="Serial number")
    nr_imei: str | None = Field(None, description="IMEI number")
    # veiculo-specific
    tipo_veiculo: str | None = Field(None, description="Vehicle type (Carro, Moto, etc.)")
    placa: str | None = Field(None, description="License plate")
    chassi: str | None = Field(None, description="Chassis number")
    possue_rastreador: bool | None = Field(None, description="Has tracker")
    ano_fabricacao: str | None = Field(None, description="Manufacturing year")
    ano_modelo: str | None = Field(None, description="Model year")
    # documento-specific
    tipo_documento: str | None = Field(None, description="Document type (RG, CNH, etc.)")
    numero_documento: str | None = Field(None, description="Document number")
    orgao_emissor: str | None = Field(None, description="Issuing authority")
    data_emissao: str | None = Field(None, description="Issue date")
    data_validade: str | None = Field(None, description="Expiry date")


class InvolvedPerson(BaseModel):
    """Person involved in the incident."""

    type: int = Field(
        ..., description="Type: 1=Comunicante, 2=Vítima, 3=Suspeito, 4=Testemunha, 99=Outros"
    )
    ds_envolvimento: str = Field(..., description="Involvement description (required by API)")
    nome_envolvido: str | None = Field(None, description="Full name if available")
    cpf: str | None = Field(None, description="CPF if available")
    ds_envolvido: str | None = Field(None, description="Observations about the person")


class IncidentPayload(BaseModel):
    """Complete API payload for creating an incident report."""

    pessoa: Person = Field(..., description="Main person reporting")
    descricao_fato: str = Field(..., description="Incident description")
    municipio_fato: str | None = Field(None, description="Municipality where incident occurred")
    bairro_fato: str | None = Field(None, description="Neighborhood where incident occurred")
    logradouro_fato: str | None = Field(None, description="Street address where incident occurred")
    lat: float | None = Field(None, description="Latitude from geocoding")
    long: float | None = Field(None, description="Longitude from geocoding")
    ponto_referencia: str | None = Field(None, description="Reference point")
    tipo_local_fato: str | None = Field(None, description="Type of location")
    momento_fato: str | None = Field(
        None, description="Date and time of incident (YYYY-MM-DD HH:MM)"
    )
    tipo_ocorrencia: list[int] | None = Field(None, description="List of incident type codes")
    meios_empregados: str | None = Field(None, description="Means employed in the incident")
    objetos_utilizados: list[dict] = Field(
        default_factory=list, description="Weapons/instruments used in the crime"
    )
    objetosOcorrencia: list[IncidentObject] = Field(
        default_factory=list, description="Objects involved"
    )
    envolvidos: list[InvolvedPerson] = Field(default_factory=list, description="People involved")
    id_status: int | None = Field(None, description="Status ID (6=Prioridade)")
    canal: str = Field(default="Chatbot", description="Channel of report")
    conversation_id: int | None = Field(None, description="Chatwoot conversation ID")
    inbox_id: int | None = Field(None, description="Chatwoot inbox ID")
    account_id: int | None = Field(None, description="Chatwoot account ID")


# ===============================
# API RESPONSE MODELS
# ===============================


class ProtocolResponse(BaseModel):
    """Response from the PDF generation API."""

    type_arquivo: str = Field(..., description="File type")
    nm_arquivo: str = Field(..., description="File name")
    path_arquivo: str = Field(..., description="File path")
    url_aws_temporaria: str = Field(..., description="Temporary AWS URL for PDF download")
    aws_location: str = Field(..., description="AWS location")


class PersonResponse(BaseModel):
    """Person information from API response."""

    id: int = Field(..., description="Person ID")
    cpf: str = Field(..., description="CPF number")
    nome_completo: str = Field(..., description="Full name")
    nome_completo_mae: str | None = Field(None, description="Mother's full name")
    telefone_contato: str | None = Field(None, description="Contact phone")
    email_contato: str | None = Field(None, description="Contact email")
    naturalidade: str | None = Field(None, description="Birth city/nationality")
    nacionalidade: str | None = Field(None, description="Nationality")
    data_nascimento: str | None = Field(None, description="Birth date")
    profissao: str | None = Field(None, description="Profession")
    sexo: str | None = Field(None, description="Gender")
    estado_civil: str | None = Field(None, description="Marital status")
    createdAt: str = Field(..., description="Creation timestamp")
    updatedAt: str = Field(..., description="Update timestamp")


class OcorrenciaResponse(BaseModel):
    """Ocorrencia information from API response."""

    id: int = Field(..., description="Incident ID")
    protocolo: str = Field(..., description="Protocol number")
    descricao_fato: str = Field(..., description="Incident description")
    momento_fato: str | None = Field(None, description="Incident date/time")
    canal: str = Field(..., description="Channel")
    id_pessoa: int = Field(..., description="Person ID")
    id_status: int = Field(..., description="Status ID")
    anonymous: bool = Field(..., description="Anonymous flag")
    pessoa: PersonResponse = Field(..., description="Person information")
    envolvidos: list = Field(default_factory=list, description="People involved")
    objetos: list = Field(default_factory=list, description="Objects involved")
    natureza: list = Field(default_factory=list, description="Incident nature")


class ApiResponse(BaseModel):
    """Complete API response structure.

    `protocolo` may be null when the upstream created the BO but failed to
    generate the PDF (e.g. Puppeteer error on their side). The caller must
    treat a null protocolo as non-retryable — the BO already exists on
    their database, retrying would duplicate it.
    """

    protocolo: ProtocolResponse | None = Field(
        None, description="Protocol information — null when PDF generation failed"
    )
    ocorrencia: OcorrenciaResponse = Field(..., description="Incident information")
